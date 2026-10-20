"""Durable outbox: one local sender, fail closed, never retry ambiguous delivery."""
import base64
import fcntl
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from email.utils import parseaddr, getaddresses
from zoneinfo import ZoneInfo
from .core import assess, excluded, hostname, now, validate_draft, write_json, read_json
from .providers import rich, text_value
from .scheduling import delivery_zone, permitted_time, notion_timezone, TIMEZONE_OPTIONS

STOP = {'Closed', 'Do Not Contact', 'Replied', 'Interview', 'Won', 'Rejected'}
SCHEMA = {
    'Research Check': {'select': {'options': [{'name':'Ready for review','color':'green'},{'name':'Needs information','color':'yellow'}]}},
    'Review Summary': {'rich_text': {}},
    'Targeting Reviewed': {'checkbox': {}},
    'Discovery Session': {'rich_text': {}},
    'Target City': {'rich_text': {}},
    'Industry': {'rich_text': {}},
    'Company Time Zone': {'select': {'options': [{'name': name} for name in TIMEZONE_OPTIONS]}},
    'Company Time Zone Verified': {'checkbox': {}},
    'Company Time Zone Source': {'url': {}},
    'Eligibility Reviewed': {'checkbox': {}}, 'Contact Purpose Reviewed': {'checkbox': {}},
    'Outreach Allowed': {'checkbox': {}}, 'Application Route': {'rich_text': {}},
    'Selected Offer': {'rich_text': {}}, 'Offer Reason': {'rich_text': {}},
    'Posting Date': {'date': {}}, 'Reply Status': {'rich_text': {}},
    'Delivery State': {'rich_text': {}}, 'Fit Reasons': {'rich_text': {}},
    'Remote Restrictions': {'rich_text': {}}, 'Compensation': {'rich_text': {}},
    'Contact Source Notes': {'rich_text': {}}
}


def setup_schema(notion, source):
    current = notion.request('data_sources/' + source, 'GET')['properties']
    missing = {k: v for k, v in SCHEMA.items() if k not in current}
    if missing:
        notion.request('data_sources/' + source, 'PATCH', {'properties': missing})
    return {'added': list(missing), 'preserved': len(current)}


def init(store):
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS outbox (
      id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, stage INTEGER NOT NULL,
      mode TEXT NOT NULL, state TEXT NOT NULL, recipient TEXT NOT NULL,
      company TEXT NOT NULL, payload TEXT NOT NULL, message_id TEXT NOT NULL,
      gmail_id TEXT DEFAULT '', thread_id TEXT DEFAULT '', error TEXT DEFAULT '',
      created_at TEXT NOT NULL, attempted_at TEXT, sent_at TEXT, due_at TEXT NOT NULL,
      UNIQUE(lead_id, stage, mode));
    CREATE TABLE IF NOT EXISTS suppressions (value TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS delivery_events (id INTEGER PRIMARY KEY, outbox_id TEXT, event TEXT, detail TEXT, at TEXT);
    ''')
    columns={row[1] for row in store.db.execute('PRAGMA table_info(outbox)')}
    if 'provider_message_id' not in columns:
        store.db.execute("ALTER TABLE outbox ADD COLUMN provider_message_id TEXT NOT NULL DEFAULT ''")
    if 'campaign_id' not in columns:
        store.db.execute("ALTER TABLE outbox ADD COLUMN campaign_id TEXT NOT NULL DEFAULT ''")
    store.db.commit()


@contextmanager
def lock(store):
    init(store)
    with (store.root / 'delivery.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another delivery command owns this state directory') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def event(store, key, kind, detail=''):
    store.db.execute('INSERT INTO delivery_events(outbox_id,event,detail,at) VALUES(?,?,?,?)', (key, kind, detail[:1000], now()))
    store.db.commit()


def rows(store):
    init(store)
    cursor = store.db.execute('SELECT * FROM outbox ORDER BY created_at,id')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def suppress(store, value, reason):
    init(store)
    store.db.execute('INSERT OR REPLACE INTO suppressions VALUES(?,?,?)', (value.strip().lower(), reason, now()))
    store.db.commit()


def suppressed(store, address, company):
    domain = address.split('@')[-1].lower()
    for value, in store.db.execute('SELECT value FROM suppressions'):
        if value == address.lower() or any(d == value or d.endswith('.' + value) for d in (domain, company)):
            return True
    return False


def policy(config, profile, preferences, exclusions):
    validate_config(config, profile)
    return {'sending': config, 'profile': profile, 'preferences': preferences, 'exclusions': exclusions,
            'stop_conditions': ['pause', 'reply', 'rejection', 'bounce', 'opt-out', 'closed job', 'suppression', 'uncertain send', 'inbox scan failure'],
            'scope': 'One Mac and one shared state directory; no cross-device delivery guarantee.'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_config(config, profile):
    if config['mode'] not in ('draft-only', 'test', 'automatic'):
        raise ValueError('Invalid sending mode')
    if config['sender'].lower() != profile['sender_email'].lower():
        raise ValueError('Sender must match profile')
    if type(config['daily_limit']) is not int or not 1 <= config['daily_limit'] <= 50 or type(config['minimum_interval_seconds']) is not int or config['minimum_interval_seconds'] < 60:
        raise ValueError('Limit must be 1–50/day; interval at least 60 seconds')
    if not 0 <= config['minimum_fit_score'] <= 100:
        raise ValueError('Invalid qualification threshold')
    start, end = config['send_hours']
    if not 0 <= start < end <= 24 or not set(config['send_weekdays']) <= set(range(7)):
        raise ValueError('Invalid sending window')
    ZoneInfo(config['timezone'])
    if config.get('schedule_basis', 'sender') not in ('sender', 'company'):
        raise ValueError('Schedule basis must be sender or company')
    if 'campaign_required' in config and type(config['campaign_required']) is not bool:
        raise ValueError('Campaign requirement must be true or false')
    if config.get('stop_on_any_inbound') is not True:
        raise ValueError('Stopping on any inbound message is mandatory')
    if config.get('test_inbox', '').lower() != profile['sender_email'].lower():
        raise ValueError('Test mode is restricted to your own sender inbox')
    if not profile.get('portfolio_url', '').startswith('https://') or 'INSERT' in profile['portfolio_url']:
        raise ValueError('A real portfolio URL is required')
    days = config.get('follow_up_days', [])
    if days != sorted(set(days)) or len(days) > 2 or any(not isinstance(d, int) or d < 3 for d in days):
        raise ValueError('Use at most two follow-ups, at least 3 days after initial send')
    if config['offers'].get('first_three', {}).get('enabled') and 'Not approved' in config['offers']['first_three']['scope']:
        raise ValueError('Define first_three offer scope and price before enabling')


def require_approval(store, manifest):
    path = store.root / 'sending-approval.json'
    if not path.exists() or read_json(path).get('sha256') != fingerprint(manifest):
        raise ValueError('Automatic sending needs approval of the current policy hash; run sending-plan')
    evidence = store.root / 'test-evidence.json'
    if not evidence.exists() or not read_json(evidence).get('reply_verified'):
        raise ValueError('Complete a live self-inbox test and verify its reply before automatic sending')


def recommend(lead, config):
    return {'offer': 'paid_test', 'reason': 'A bounded paid design checks fit without promising unpaid work; advertised application instructions take priority.', 'scope': config['offers']['paid_test']['scope']}


def field(props, name):
    return text_value(props.get(name, {}))


def remote_lead(store, notion, lead, persist=True):
    if not lead.get('notion_page_id'):
        raise ValueError('Sync lead to Notion before queueing')
    page = notion.request('pages/' + lead['notion_page_id'], 'GET')
    if page.get('archived') or page.get('in_trash'):
        raise ValueError('Notion record is archived')
    p = page['properties']
    if page.get('_outreach_original') and field(p,'Deduplication Key')!=lead['id']:
        raise ValueError('Original Outreach record is not owned by this research record; history preserved')
    lead['targeting_reviewed'] = p.get('Targeting Reviewed', {}).get('checkbox', False)
    lead['company_time_zone'] = notion_timezone(p.get('Company Time Zone', {}))
    lead['company_time_zone_verified'] = p.get('Company Time Zone Verified', {}).get('checkbox', False)
    lead['company_time_zone_source'] = p.get('Company Time Zone Source', {}).get('url') or ''
    remote_status = (p.get('STATUS', {}).get('status') or {}).get('name', '')
    lead['notion_status'] = remote_status
    lead['status'] = remote_status
    lead['approved'] = p.get('Approved', {}).get('checkbox', False)
    if page.get('_outreach_original') and remote_status == 'Ready':
        # Old sender's Ready is not approval of a new AI-researched application.
        lead['approved']=False
    lead['do_not_contact'] = p.get('Do Not Contact', {}).get('checkbox', False)
    for name, key in [('Eligibility Reviewed', 'eligibility_reviewed'), ('Contact Purpose Reviewed', 'contact_purpose_reviewed'), ('Outreach Allowed', 'outreach_allowed')]:
        lead[key] = p.get(name, {}).get('checkbox', False)
    # Recipient edits must match the address in the original evidence.
    address = p.get('EMAIL', {}).get('email') or ''
    lead['email'] = address.lower().strip()
    lead['application_route'] = field(p, 'Application Route')
    lead['selected_offer'] = field(p, 'Selected Offer') or 'paid_test'
    lead['contact_review_notes'] = field(p, 'Contact Source Notes')
    lead['draft'] = {**lead.get('draft', {}), 'subject': field(p, 'email SUBJECT'), 'body': field(p, 'email body')}
    lead['scheduled_time'] = (p.get('Scheduled Time', {}).get('date') or {}).get('start')
    if remote_status == 'Approve':
        # Only this explicit Notion decision represents the human review.
        # Scraped/AI fields never supply approval; source and delivery gates
        # still run before a queue reservation and immediately before sending.
        from .review import sourced_candidate, REVIEW_FLAGS, ATTESTATION
        lead = sourced_candidate(lead)
        lead.update(status='Ready', approved=True, **{key:True for key in REVIEW_FLAGS})
        note='Notion STATUS=Approve: '+ATTESTATION
        if note not in lead['contact_review_notes']:
            lead['contact_review_notes']=(lead['contact_review_notes']+'\n'+note).strip()
    if hasattr(notion,'assert_contact_available'):notion.assert_contact_available(lead)
    if persist:store.save(lead)
    return lead


def check_draft(lead, profile, config):
    draft = validate_draft(dict(lead['draft'], lead_id=lead['id']), lead, profile)
    if profile['portfolio_url'] not in draft['body']:
        raise ValueError('Draft must include your exact portfolio URL')
    offer = lead.get('selected_offer', 'paid_test')
    if offer not in config['offers'] or not config['offers'][offer]['enabled']:
        raise ValueError('Selected offer is not enabled')
    text = draft['body'].lower()
    # An invitation to "feel free to reply" does not offer unpaid work.
    # Other free-work language, including a later promise in the same sentence,
    # must still be checked against the enabled offer.
    offer_text = re.sub(r'\bfeel\s+free\b', '', text)
    if re.search(r'\b(?:free|complimentary|no.cost|unpaid)\b', offer_text) and offer not in ('audit', 'sample', 'first_three'):
        raise ValueError('Unapproved free-work promise')
    if re.search(r'(?:three|3).{0,25}(?:free|complimentary)|(?:free|complimentary).{0,25}(?:three|3)', offer_text) and offer != 'first_three':
        raise ValueError('Three-free-email offer is disabled')
    if offer in ('audit', 'sample', 'first_three') and config['offers'][offer]['scope'] not in draft['body']:
        raise ValueError('Optional offer must include its exact approved scope and limits')
    if re.search(r'guarantee.{0,30}(?:revenue|sales|conversion)|i (?:accept|agree to) (?:the |your )?contract', text):
        raise ValueError('Unsupported guarantee or contractual commitment')
    return draft


def gate(store, lead, config, profile, prefs, exclusions, follow=False):
    if lead.get('target_session') and config['mode'] != 'test':
        from .targeting import target_check
        if target_check(lead) or not lead.get('targeting_reviewed'):
            raise ValueError('Research needs a sourced city, company type and industry. See Review Summary in Notion')
    if config['mode'] != 'test':
        delivery_zone(config, lead)
    if store.paused():
        raise ValueError('Agent is paused')
    if not exclusions.get('confirmed'):
        raise ValueError('Confirm exclusion list before delivery')
    if config['mode'] == 'automatic' and lead.get('is_demo'):
        raise ValueError('Demo opportunities cannot be sent to external recipients')
    assessment = assess(lead, prefs, exclusions)
    if assessment['status'] in ('Closed', 'Do Not Contact') or lead.get('status') in STOP or lead.get('do_not_contact'):
        raise ValueError('Opportunity is closed, contacted or suppressed')
    address = lead.get('email', '')
    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', address):
        raise ValueError('No valid published application address; use official portal')
    company = hostname(lead.get('website') or lead['url'])
    if suppressed(store, address, company):
        raise ValueError('Suppression list blocks this contact')
    if address not in lead.get('email_candidates', []) or not lead.get('contact_source_url'):
        raise ValueError('Recipient does not match published evidence')
    if lead.get('kind') not in config['allowed_kinds'] or lead.get('country') not in prefs['countries']:
        raise ValueError('Outside approved targeting')
    if config['mode'] != 'test':
        if assessment['score'] < config['minimum_fit_score']:
            raise ValueError('Below qualification threshold')
        allowed_statuses = ('Ready',) if config['require_row_approval'] else ('Ready', 'Draft')
        if not follow and lead.get('status') not in allowed_statuses:
            raise ValueError('Review the message in Notion and set STATUS to Approve')
        if config['require_row_approval'] and not lead.get('approved'):
            raise ValueError('Review the message in Notion and set STATUS to Approve')
        if not all(lead.get(k) for k in ('eligibility_reviewed', 'contact_purpose_reviewed', 'outreach_allowed')) or not lead.get('contact_review_notes'):
            raise ValueError('Review eligibility, relevant contact purpose and outreach permission; record source notes')
        if lead['kind'] == 'Posted Job':
            if lead.get('application_route', '').strip().lower() != 'email':
                raise ValueError('Portal-only or unknown application route; no email application')
            if config['require_confirmed_job_eligibility'] and lead.get('remote_eligibility') != 'Confirmed':
                raise ValueError('Worldwide/Thailand applicant eligibility unconfirmed')
            if lead.get('rate_per_email') is None or lead.get('currency') != 'USD':
                raise ValueError('Job compensation requires review; hourly rates cannot be assumed per-email')
        elif not config['allow_unknown_cold_budget'] and lead.get('rate_per_email') is None:
            raise ValueError('Cold prospect budget is unknown')
        if lead['kind'] == 'Cold Outreach' and not config.get('business_postal_address', '').strip():
            raise ValueError('Configure an appropriate business postal address for cold-outreach identity/footer')
    return check_draft(lead, profile, config)


def queue(store, lead, config, profile, prefs, exclusions, stage=0, due=None):
    init(store)
    validate_config(config, profile)
    if config['mode'] == 'draft-only':
        return {'state': 'draft-only', 'offer': recommend(lead, config)}
    draft = gate(store, lead, config, profile, prefs, exclusions, follow=stage > 0)
    company = hostname(lead.get('website') or lead['url'])
    existing = rows(store)
    replace_key = None
    for item in existing:
        if item['lead_id'] == lead['id'] and item['mode'] == config['mode'] and item['stage'] == stage and item['state'] == 'blocked' and not item['attempted_at']:
            replace_key = item['id']
            continue
        if item['mode'] == config['mode'] and item['stage'] == 0 and stage == 0 and (item['company'] == company or item['recipient'] == lead['email']):
            raise ValueError('Company or recipient already has an application in this mode')
    from . import campaigns
    campaign_id=campaigns.assignment(store,config)
    recipient = config['test_inbox'] if config['mode'] == 'test' else lead['email']
    payload = dict(draft, draft_hash=fingerprint(draft), offer=lead.get('selected_offer', 'paid_test'), original_recipient=lead['email'])
    if config['mode'] == 'test':
        payload['subject'] = '[AGENT TEST] ' + payload['subject']
        payload['body'] = 'TEST ONLY. Intended business: ' + lead.get('company', '') + '\n\n' + payload['body']
    elif lead['kind'] == 'Cold Outreach':
        from .signature import with_footer
        payload['body']=with_footer(payload['body'],profile,config['cold_outreach_footer']+'\n'+config['business_postal_address'])
    due_at = due or lead.get('scheduled_time') or now()
    due_time = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
    if due_time.tzinfo is None:
        due_time = due_time.replace(tzinfo=delivery_zone(config, lead))
    due_at = due_time.astimezone(timezone.utc).isoformat()
    key = hashlib.sha256((lead['id'] + ':' + str(stage) + ':' + config['mode']).encode()).hexdigest()[:32]
    message_id = '<shine-' + key + '@' + config['sender'].split('@')[1] + '>'
    if replace_key:
        store.db.execute("UPDATE outbox SET state='queued',payload=?,recipient=?,error='',due_at=?,campaign_id=? WHERE id=?", (json.dumps(payload), recipient, due_at, campaign_id, replace_key))
        store.db.commit()
        event(store, replace_key, 'preflight-requeued')
        return {'id': replace_key, 'state': 'queued', 'recipient': recipient}
    store.db.execute('INSERT OR IGNORE INTO outbox(id,lead_id,stage,mode,state,recipient,company,payload,message_id,created_at,due_at,campaign_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (key, lead['id'], stage, config['mode'], 'queued', recipient, company, json.dumps(payload), message_id, now(), due_at,campaign_id))
    store.db.commit()
    event(store, key, 'queued')
    return {'id': key, 'state': 'queued', 'recipient': recipient}


def change(store, key, state, **values):
    allowed = {'gmail_id', 'thread_id', 'error', 'attempted_at', 'sent_at', 'provider_message_id'}
    if not set(values) <= allowed:
        raise ValueError('Invalid outbox fields')
    store.db.execute('UPDATE outbox SET state=?' + ''.join(',' + k + '=?' for k in values) + ' WHERE id=?', [state] + list(values.values()) + [key])
    store.db.commit()
    event(store, key, state, values.get('error', ''))


def recheck(lead, prefs, research):
    if lead['kind'] == 'Posted Job':
        text = research(lead['url'])
        if re.search(r'no longer (?:accepting|available)|(?:job|position|vacancy) (?:is |has been )?(?:closed|filled)|applications (?:are )?closed', text, re.I):
            raise ValueError('Job page indicates vacancy is closed')
        fresh = dict(lead, source_text=text)
        if re.search(r'(?:do not|don.t|no) (?:apply|applications?) (?:by |via |through )?email|apply (?:only |exclusively )?(?:through|via|using) (?:our |the )?(?:portal|application form|website)|applications? (?:only )?(?:through|via) (?:the )?(?:portal|form)', text, re.I):
            raise ValueError('Current application instructions require a portal or prohibit email')
        assessment = assess(fresh, prefs, {'confirmed': True})
        if assessment['status'] == 'Closed':
            raise ValueError('Current job requirements conflict with profile')
        # A generic search page returning 200 is not proof that this job exists.
        words = [w for w in re.findall(r'[a-z]+', lead['title'].lower()) if len(w) > 3]
        if not words or sum(w in text.lower() for w in words) < min(2, len(words)):
            raise ValueError('Could not re-identify role on current application page')
    contact = research(lead['contact_source_url'])
    if lead['email'].lower() not in contact.lower():
        raise ValueError('Recipient no longer appears in current published contact source')


def message_text(message):
    def decode(part):
        output = ''
        data = part.get('body', {}).get('data', '')
        if data:
            try:
                output = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', errors='replace')
            except (ValueError, TypeError):
                pass
        return output + '\n' + '\n'.join(decode(p) for p in part.get('parts', []))
    return (message.get('snippet', '') + '\n' + decode(message.get('payload', {})))[:100000]


def inbound_reason(message, sender, recipient, ids, sent_at):
    if 'DRAFT' in message.get('labelIds', []):
        return ''
    if int(message.get('internalDate', '0')) < int(datetime.fromisoformat(sent_at).timestamp() * 1000):
        return ''
    headers = {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}
    address = parseaddr(headers.get('from', ''))[1].lower()
    if address == sender.lower() or 'SENT' in message.get('labelIds', []):
        return ''
    text = (headers.get('subject', '') + '\n' + message_text(message)).lower()
    if 'mailer-daemon' in address or 'postmaster' in address:
        if recipient.lower() in text or any(mid.lower() in text for mid in ids):
            return 'Bounce or delivery notice; manual review required'
        return ''
    if re.search(r'\bunsubscribe\b|\bremove me\b|\bstop (?:emailing|contacting)\b|\bdo not contact\b', text):
        return 'Opt-out or suppression request; manual review required'
    if re.search(r'\bnot interested\b|\brejected\b|\bposition.{0,20}filled\b', text):
        return 'Reply/rejection; manual review required'
    return 'Inbound reply; manual review required'


def provider_reference(store, gmail, item, sender):
    """Use the RFC Message-ID read back using the immutable Gmail receipt."""
    if item.get('provider_message_id'):
        return item['provider_message_id']
    message=gmail.message(item['gmail_id'])
    if not isinstance(message,dict) or message.get('id')!=item['gmail_id']:
        raise ValueError('Sent-message receipt could not be verified')
    headers={h['name'].lower():h['value'] for h in message.get('payload',{}).get('headers',[])}
    reference=headers.get('message-id','').strip()
    if parseaddr(headers.get('from',''))[1].lower()!=sender.lower() or item['recipient'].lower() not in {a.lower() for _,a in getaddresses([headers.get('to','')])} or not re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',reference):
        raise ValueError('Sent-message sender or RFC Message-ID could not be verified')
    change(store,item['id'],item['state'],provider_message_id=reference)
    return reference


def scan_item(store, gmail, item, config):
    if item['mode'] == 'test':
        return ''
    if not item.get('thread_id') or not item.get('sent_at'):
        return ''
    payload = json.loads(item['payload'])
    recipient = item['recipient']
    messages = gmail.thread(item['thread_id'])
    messages += gmail.related(recipient, datetime.fromisoformat(item['sent_at']).timestamp())
    for message in messages:
        # related() only retrieves same-recipient or delivery-system mail.
        reason = inbound_reason(message, config['sender'], recipient, [item['message_id'], item.get('provider_message_id','') or item['message_id']], item['sent_at'])
        if reason:
            suppress(store, payload['original_recipient'], reason)
            suppress(store, item['company'], reason)
            lead = store.get(item['lead_id'])
            lead.update(reply_status=reason, last_reply_at=now(), status='Replied', delivery_dirty=True)
            if 'Opt-out' in reason or 'Bounce' in reason:
                lead['status'] = 'Do Not Contact'
            lead['follow_up_date'] = None
            store.save(lead)
            for candidate in rows(store):
                if candidate['lead_id'] == item['lead_id'] and candidate['state'] == 'queued':
                    change(store, candidate['id'], 'cancelled', error=reason)
            event(store, item['id'], 'inbound', reason)
            return reason
    return ''


def poll(store, gmail, config):
    results = []
    for item in rows(store):
        if item['state'] == 'sent' and item['mode'] == config['mode']:
            reason = scan_item(store, gmail, item, config)
            if reason:
                results.append({'id': item['id'], 'reason': reason})
    return results


def tick(store, gmail, notion, config, profile, prefs, exclusions, research, clock=None):
    injected_clock = clock is not None
    clock = clock or datetime.now(timezone.utc)
    validate_config(config, profile)
    with lock(store):
        if config['mode'] == 'draft-only' or store.paused():
            return {'state': 'paused' if store.paused() else 'draft-only'}
        if config['mode'] == 'automatic':
            require_approval(store, policy(config, profile, prefs, exclusions))
        if gmail.identity() != config['sender'].lower():
            raise ValueError('Gmail account does not match sender')
        # Any scan failure prevents all new sending, including follow-ups.
        poll(store, gmail, config)
        current = rows(store)
        if any(i['state'] in ('sending', 'uncertain') for i in current):
            raise ValueError('Uncertain delivery blocks sending; reconcile it first')
        if config['mode'] == 'automatic' and config.get('schedule_basis', 'sender') == 'sender' and not permitted_time(config, clock):
            return {'state': 'outside sending window'}
        tz = ZoneInfo(config['timezone'])
        today = clock.astimezone(tz).date()
        attempts = [i for i in current if i['attempted_at'] and datetime.fromisoformat(i['attempted_at']).astimezone(tz).date() == today]
        if len(attempts) >= config['daily_limit']:
            return {'state': 'daily limit reached'}
        all_attempts = [datetime.fromisoformat(i['attempted_at']) for i in current if i['attempted_at']]
        if all_attempts and (clock - max(all_attempts)).total_seconds() < config['minimum_interval_seconds']:
            return {'state': 'waiting for send interval'}
        candidates = [i for i in current if i['state'] == 'queued' and i['mode'] == config['mode'] and datetime.fromisoformat(i['due_at']) <= clock]
        if not candidates:
            return {'state': 'queue empty'}
        from . import campaigns
        if config['mode']=='automatic' and config.get('campaign_required'):
            current_campaign=campaigns.active(store)
            if not current_campaign:return {'state':'choose a campaign target'}
            if not current_campaign['remaining']:return {'state':'campaign target reached'}
            candidates=[c for c in candidates if c.get('campaign_id')==current_campaign['id']]
            if not candidates:return {'state':'no queued messages assigned to active campaign'}
        item = None
        for candidate in candidates:
            if config['mode'] == 'automatic' and config.get('schedule_basis') == 'company':
                try:
                    candidate_lead = remote_lead(store, notion, store.get(candidate['lead_id']))
                    if not permitted_time(config, clock, candidate_lead):
                        continue
                except Exception as exc:
                    change(store, candidate['id'], 'blocked', error=str(exc))
                    continue
            item = candidate
            break
        if item is None:
            return {'state': 'waiting for company-local window or timezone review'}
        try:
            lead = remote_lead(store, notion, store.get(item['lead_id']))
            draft = gate(store, lead, config, profile, prefs, exclusions, follow=item['stage'] > 0)
            payload = json.loads(item['payload'])
            if lead['email'] != payload['original_recipient']:
                raise ValueError('Recipient changed after queueing')
            if item['stage'] == 0:
                expected_subject = ('[AGENT TEST] ' if item['mode'] == 'test' else '') + draft['subject']
                expected_body = draft['body']
                if payload['subject'] != expected_subject or payload.get('draft_hash') != fingerprint(draft) or payload['offer'] != lead.get('selected_offer', 'paid_test'):
                    raise ValueError('Draft or offer changed; review and replace unsent queue item')
            if config['mode'] == 'automatic':
                recheck(lead, prefs, research)
                if item['stage'] == 0 and gmail.prior_contact(lead['email']):
                    raise ValueError('Gmail Sent already contains contact with this recipient; manual review required')
            # Inbox checked again just before a follow-up is sent.
            if item['stage']:
                initial = next(i for i in current if i['lead_id'] == item['lead_id'] and i['stage'] == 0 and i['mode'] == item['mode'])
                if scan_item(store, gmail, initial, config):
                    return {'state': 'cancelled after reply'}
            if store.paused():
                raise ValueError('Agent paused during preflight')
            if config['mode'] == 'automatic':
                dispatch_clock = clock if injected_clock else datetime.now(timezone.utc)
                if not permitted_time(config, dispatch_clock, lead):
                    return {'state': 'waiting for company-local window'}
                clock = dispatch_clock
        except Exception as exc:
            change(store, item['id'], 'blocked', error=str(exc))
            if config['mode']=='automatic':
                reset=store.get(item['lead_id'])
                reset.update(approval_reset_pending=True, review_hold=str(exc)[:1000],review_feedback_dirty=True)
                store.save(reset)
            return {'state': 'blocked', 'id': item['id'], 'error': str(exc)}
        # Commit BEFORE request. A crash thereafter never results in blind resend.
        if config['mode']=='automatic' and config.get('campaign_required'):
            campaigns.claim(store,item,clock.isoformat())
        else:
            change(store, item['id'], 'sending', attempted_at=clock.isoformat())
        try:
            result = gmail.send(config['sender'], item['recipient'], payload['subject'], payload['body'], item['message_id'], item.get('thread_id', ''), payload.get('reply_to', ''))
            if not result.get('id') or not result.get('threadId'):
                raise ValueError('Incomplete Gmail send response')
        except Exception:
            change(store, item['id'], 'uncertain', error='Send outcome unknown. Reconcile by Message-ID; never blindly retry.')
            return {'state': 'uncertain', 'id': item['id']}
        change(store, item['id'], 'sent', gmail_id=result['id'], thread_id=result['threadId'], sent_at=clock.isoformat(), error='')
        record_sent(store, item, result, clock.isoformat())
        try:
            sent_item=next(row for row in rows(store) if row['id']==item['id'])
            provider_reference(store,gmail,sent_item,config['sender'])
        except Exception:
            event(store,item['id'],'metadata pending','Send receipt saved. Fetch provider Message-ID before any follow-up.')
        return {'state': 'sent', 'id': item['id'], 'recipient': item['recipient']}


def record_sent(store, item, result, sent_at):
    if item['mode'] == 'test':
        write_json(store.root / 'test-evidence.json', {'outbox_id': item['id'], 'gmail_id': result['id'], 'thread_id': result['threadId'], 'sent_at': sent_at, 'reply_verified': False})
    else:
        lead = store.get(item['lead_id'])
        lead.update(status='Sent', gmail_message_id=result['id'], gmail_thread_id=result['threadId'], delivery_dirty=True)
        lead.setdefault('sent_at', sent_at)
        lead['follow_up_date'] = None
        store.save(lead)


def reconcile(store, gmail):
    output = []
    with lock(store):
        for item in rows(store):
            if item['state'] not in ('sending', 'uncertain'):
                continue
            result = gmail.find_sent(item['message_id'])
            if result:
                stamp = item['attempted_at'] or now()
                change(store, item['id'], 'sent', gmail_id=result['id'], thread_id=result['threadId'], sent_at=stamp, error='')
                record_sent(store, item, result, stamp)
                output.append({'id': item['id'], 'state': 'sent'})
            else:
                change(store, item['id'], 'uncertain', error='Not found in Sent yet; absence is not proof of non-delivery. Inspect Gmail manually.')
                output.append({'id': item['id'], 'state': 'uncertain'})
    return output


def reconcile_receipt(store, gmail, outbox_id, gmail_id, sender):
    """Recover an uncertain send only from an exact, explicitly selected Sent receipt."""
    with lock(store):
        item=next((r for r in rows(store) if r['id']==outbox_id),None)
        if not item or item['state'] not in ('sending','uncertain'):
            raise ValueError('Select an existing uncertain outbox item')
        message=gmail.message(gmail_id)
        if message.get('id')!=gmail_id or 'SENT' not in message.get('labelIds',[]):
            raise ValueError('Selected message is not a verified Sent receipt')
        headers={h['name'].lower():h['value'] for h in message.get('payload',{}).get('headers',[])}
        payload=json.loads(item['payload'])
        recipients={a.lower() for _,a in getaddresses([headers.get('to','')])}
        if parseaddr(headers.get('from',''))[1].lower()!=sender.lower() or recipients!={item['recipient'].lower()} or headers.get('subject')!=payload['subject']:
            raise ValueError('Sent sender, recipient or subject does not match queued payload')
        def plain(part):
            if part.get('mimeType')=='text/plain':
                data=part.get('body',{}).get('data','')
                return base64.urlsafe_b64decode(data+'='*(-len(data)%4)).decode('utf-8')
            return '\n'.join(plain(p) for p in part.get('parts',[]))
        body=plain(message.get('payload',{})).replace('\r\n','\n').strip()
        if body!=payload['body'].replace('\r\n','\n').strip():
            raise ValueError('Sent body does not exactly match queued payload')
        attempted=datetime.fromisoformat(item['attempted_at']).timestamp()
        accepted=int(message.get('internalDate','0'))/1000
        if not attempted-5<=accepted<=attempted+600:
            raise ValueError('Sent receipt is outside this attempt’s ten-minute window')
        reference=headers.get('message-id','').strip()
        if not re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',reference):
            raise ValueError('Sent receipt has no valid provider Message-ID')
        result={'id':gmail_id,'threadId':message['threadId']}
        stamp=datetime.fromtimestamp(accepted,timezone.utc).isoformat()
        change(store,item['id'],'sent',gmail_id=gmail_id,thread_id=result['threadId'],provider_message_id=reference,sent_at=stamp,error='')
        record_sent(store,item,result,stamp)
        return {'id':item['id'],'state':'sent','message':'Exact Sent receipt linked; no email sent by this command.'}


def followups(store, gmail, notion, config, profile, prefs, exclusions):
    if not config['follow_ups_enabled'] or config['mode'] != 'automatic':
        return []
    require_approval(store, policy(config, profile, prefs, exclusions))
    poll(store, gmail, config)
    output = []
    current = rows(store)
    for item in current:
        if item['state'] != 'sent' or item['stage'] != 0 or item['mode'] != 'automatic':
            continue
        if config.get('campaign_required'):
            from . import campaigns
            if not campaigns.permitted(store,item):continue
        lead = remote_lead(store, notion, store.get(item['lead_id']))
        if suppressed(store, lead['email'], item['company']) or lead['status'] in STOP:
            continue
        for stage, days in enumerate(config['follow_up_days'], 1):
            if any(i['lead_id'] == item['lead_id'] and i['mode'] == item['mode'] and i['stage'] == stage for i in current):
                continue
            due = datetime.fromisoformat(item['sent_at']) + timedelta(days=days)
            if due > datetime.now(timezone.utc):
                continue
            reference=provider_reference(store,gmail,item,config['sender'])
            queued = queue(store, lead, config, profile, prefs, exclusions, stage, due.isoformat())
            entry = next(i for i in rows(store) if i['id'] == queued['id'])
            payload = json.loads(entry['payload'])
            original = json.loads(item['payload'])
            payload.update(subject=original['subject'], body='Hi ' + lead['company'] + ' team,\n\nI wanted to follow up on my email about freelance email design support. Would a small paid Figma design test be useful? If the timing is not right, no problem.\n\nPortfolio: ' + profile['portfolio_url'] + '\n\nShine', reply_to=reference)
            from .signature import with_signature
            payload['body']=with_signature(payload['body'],profile)
            if lead['kind'] == 'Cold Outreach':
                from .signature import with_footer
                payload['body']=with_footer(payload['body'],profile,config['cold_outreach_footer']+'\n'+config['business_postal_address'])
            store.db.execute('UPDATE outbox SET payload=?,thread_id=? WHERE id=?', (json.dumps(payload), item['thread_id'], queued['id']))
            store.db.commit()
            lead['follow_up_date'] = due.isoformat()
            lead['delivery_dirty'] = True
            store.save(lead)
            output.append(queued)
    return output


def sync_delivery(store, notion):
    result = {'updated': 0, 'errors': []}
    current = rows(store)
    for lead in store.leads():
        if not lead.get('notion_page_id'):
            continue
        items = [i for i in current if i['lead_id'] == lead['id'] and i['mode'] == 'automatic']
        if not items and not lead.get('delivery_dirty') and not lead.get('review_feedback_dirty'):
            continue
        try:
            props = {'Reply Status': {'rich_text': rich(lead.get('reply_status', ''))}}
            if lead.get('review_feedback_dirty') and not items:
                props.update({'Delivery State':{'rich_text':rich('Held: '+lead.get('review_hold',''))},
                              'Error':{'rich_text':rich(lead.get('review_hold',''))}})
            if items:
                latest = items[-1]
                props.update({'Delivery State': {'rich_text': rich(latest['state'])}, 'Error': {'rich_text': rich(latest['error'])}})
            if lead.get('delivery_dirty'):
                remote = notion.request('pages/' + lead['notion_page_id'], 'GET')
                remote_status = (remote.get('properties', {}).get('STATUS', {}).get('status') or {}).get('name', '')
                props['Follow-up Date'] = {'date': {'start': lead['follow_up_date']} if lead.get('follow_up_date') else None}
                if (remote_status not in STOP or lead['status'] == 'Do Not Contact') and not (remote_status=='Approve' and lead['status']=='Ready'):
                    props['STATUS'] = {'status': {'name': lead['status']}}
                if items and items[-1]['state']=='queued':
                    props['Scheduled Time']={'date':{'start':items[-1]['due_at']}}
                for key, name in [('gmail_message_id', 'Gmail Message ID'), ('gmail_thread_id', 'Gmail Thread ID')]:
                    if lead.get(key):
                        props[name] = {'rich_text': rich(lead[key])}
                for key, name in [('sent_at', 'sent time'), ('last_reply_at', 'Last Reply Time')]:
                    if lead.get(key):
                        props[name] = {'date': {'start': lead[key]}}
                if lead['status'] == 'Do Not Contact':
                    props['Do Not Contact'] = {'checkbox': True}
                    props['Approved'] = {'checkbox': False}
            if lead.get('approval_reset_pending'):
                remote=notion.request('pages/'+lead['notion_page_id'],'GET')
                remote_status=(remote.get('properties',{}).get('STATUS',{}).get('status') or {}).get('name','')
                if remote_status not in STOP | {'Sent','Sending'}:
                    props.update({'STATUS':{'status':{'name':'Needs Review'}},'Approved':{'checkbox':False}})
                # Leave failed records visibly in Notion; a later Approve is a
                # new human decision. Failed PATCH retains this local hold.
            notion.request('pages/' + lead['notion_page_id'], 'PATCH', {'properties': props})
            if lead.pop('approval_reset_pending',False):lead.update(approved=False,status=remote_status if remote_status in STOP | {'Sent','Sending'} else 'Needs Review')
            lead['review_feedback_dirty'] = False
            lead['delivery_dirty'] = False
            store.save(lead)
            result['updated'] += 1
        except Exception as exc:
            result['errors'].append({'id': lead['id'], 'error': str(exc)[:200]})
    return result


def queue_ready(store, notion, config, profile, prefs, exclusions):
    """Queue eligible local records from current Notion review; no duplicate sends."""
    if config['mode'] != 'automatic' or store.paused():
        return []
    require_approval(store, policy(config, profile, prefs, exclusions))
    output = []
    for lead in store.leads():
        if not lead.get('notion_page_id') or lead.get('is_demo') or not lead.get('draft'):
            continue
        if any(i['lead_id'] == lead['id'] and i['mode'] == config['mode'] and (i['state'] != 'blocked' or i['attempted_at']) for i in rows(store)):
            continue
        try:
            if lead.get('approval_reset_pending'):
                raise ValueError('A message changed or failed preflight. Wait for its Notion review reset, then set STATUS to Approve again.')
            lead = remote_lead(store, notion, lead)
            from .review import next_window
            due=next_window(config,lead) if config.get('schedule_basis')=='company' else None
            item=queue(store, lead, config, profile, prefs, exclusions,due=due)
            output.append(item)
            # Scheduling feedback is written by sync_delivery, without changing
            # the human's Approve status or rewriting the message.
            lead['delivery_dirty']=True;store.save(lead)
        except (ValueError, KeyError) as exc:
            output.append({'lead_id': lead['id'], 'held': str(exc)[:200]})
            lead['review_hold']=str(exc)[:1000];lead['review_feedback_dirty']=True;store.save(lead)
    return output
