"""Short-lived worker; existing qualification, research and message rules reused."""
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from email.utils import parseaddr, getaddresses
from zoneinfo import ZoneInfo
from acquisition_agent import delivery
from acquisition_agent.core import Store, hostname
from acquisition_agent.providers import Notion, rich
from acquisition_agent.gmail import Gmail
from acquisition_agent.discovery import research
from acquisition_agent.scheduling import permitted_time
from .queue import digest
from .github_state import StateError


def settings_hash(settings):
    return digest({'github_schema': 1, 'settings': settings, 'followups': 'disabled'})


class Worker:
    def __init__(self, queue, settings, gmail, notion, researcher=research, report=None):
        self.q, self.s, self.gmail, self.notion, self.research = queue, settings, gmail, notion, researcher
        self.report = report or (lambda stage: None)
        delivery.validate_config(settings['sending'], settings['profile'])
        cfg=settings['sending']
        if cfg['send_hours']!=[8,11] or cfg['send_weekdays']!=[0,1,2,3,4] or cfg['minimum_interval_seconds']<180:
            raise ValueError('GitHub sender requires weekday 08–11 company-local windows and three-minute spacing')
        if settings['sending'].get('follow_up_days'):
            raise ValueError('Disable follow-ups for cloud pilot')
        if settings['sending'].get('schedule_basis') != 'company':
            raise ValueError('Cloud pilot requires verified company-local scheduling')

    def local(self, folder):
        store = Store(Path(folder))
        delivery.init(store)
        for record in self.q.db.list('suppression'):
            delivery.suppress(store, record['value'], record['reason'])
        return store

    def preflight(self, item, store):
        lead = self.q.db.get('lead_' + item['lead_id'])['data']
        lead = delivery.remote_lead(store, self.notion, dict(lead), persist=False)
        if lead.get('notion_status')!='Approve':raise ValueError('Notion approval was withdrawn')
        self.target_matches(lead, item['campaign'])
        draft = delivery.gate(store, lead, self.s['sending'], self.s['profile'], self.s['preferences'], self.s['exclusions'])
        if lead['email'] != item['recipient'] or hostname(lead.get('website') or lead['url']) != item['company']:
            raise ValueError('Recipient/company changed; create a new reviewed campaign item')
        if digest(draft) != item['draft_hash'] or lead['company_time_zone'] != item['company_timezone']:
            raise ValueError('Draft or timezone changed after queueing')
        return lead

    def sync_leads(self):
        # Research writes to Notion on the Mac. Never recreate a deleted row.
        return {'synced':0}

    def target_matches(self, lead, campaign_id):
        from acquisition_agent.targeting import validate_spec, city_matches
        campaign=self.q.db.get('campaign_'+campaign_id)
        if not campaign:raise ValueError('Unknown campaign')
        from acquisition_agent.targeting import target_check
        if not lead.get('target_session') or target_check(lead):raise ValueError('Cloud campaign requires sourced location/type/industry evidence')
        if not campaign.get('target'):return
        target=validate_spec(campaign['target'],self.s['preferences'])
        if (lead.get('country')!=target['country'] or not city_matches(lead.get('location_city',''),target['city']) or
            lead.get('type')!=target['company_type'] or lead.get('kind')!=target['kind'] or
            (target['industries'] and lead.get('industry') not in target['industries'])):
            raise ValueError('Lead does not match this campaign targeting')

    def enqueue(self, lead_id, campaign_id):
        record = self.q.db.get('lead_' + lead_id)
        if not record: raise ValueError('Import a researched lead first')
        self.target_matches(record['data'],campaign_id)
        with tempfile.TemporaryDirectory() as folder:
            store = self.local(folder)
            try:
                lead = delivery.remote_lead(store, self.notion, dict(record['data']), persist=False)
                if lead.get('notion_status')!='Approve':raise ValueError('Set STATUS to Approve in Notion')
                draft = delivery.gate(store, lead, self.s['sending'], self.s['profile'], self.s['preferences'], self.s['exclusions'])
            finally: store.db.close()
        from acquisition_agent.review import next_window
        due = datetime.fromisoformat(lead.get('scheduled_time') or next_window(self.s['sending'],lead))
        if due.tzinfo is None: raise ValueError('Scheduled Time must contain a timezone offset')
        body = draft['body']
        if lead['kind'] == 'Cold Outreach':
            from acquisition_agent.signature import with_footer
            body=with_footer(body,self.s['profile'],self.s['sending']['cold_outreach_footer']+'\n'+self.s['sending']['business_postal_address'])
        key = digest([lead_id, 'initial', 'automatic'])[:32]
        result=self.q.enqueue({'id': key, 'campaign': campaign_id, 'lead_id': lead_id,
            'recipient': lead['email'], 'company': hostname(lead.get('website') or lead['url']),
            'company_timezone': lead['company_time_zone'], 'due_at': due.timestamp(),
            'draft_hash': digest(draft), 'subject': draft['subject'], 'body': body,
            'message_id': '<shine-github-' + key + '@' + self.s['sending']['sender'].split('@')[1] + '>'})
        if result['state']=='queued':
            self.notion.request('pages/'+lead['notion_page_id'],'PATCH',{'properties':{'Scheduled Time':{'date':{'start':datetime.fromtimestamp(result['due_at'],timezone.utc).isoformat()}},'Delivery State':{'rich_text':rich('Queued for company-local weekday 08:00–11:00')}}})
        return result

    def poll(self):
        # Errors bubble up: inbox scan failure prevents all subsequent sends.
        for item in self.q.db.list('outbox'):
            if item['state'] != 'sent' or item.get('mode') == 'test' or item.get('reply_reason'): continue
            messages = self.gmail.thread(item['thread_id'])
            messages += self.gmail.related(item['recipient'], item['attempted_at'])
            for message in messages:
                reason = delivery.inbound_reason(message, self.s['sending']['sender'], item['recipient'],
                    [item['message_id'],item.get('provider_message_id','')], datetime.fromtimestamp(item['attempted_at'], timezone.utc).isoformat())
                if reason:
                    self.q.suppress([item['recipient'], item['company']], reason)
                    def remember(tx):
                        current=tx.get('outbox_'+item['id']);current['reply_reason']=reason;tx.put('outbox_'+item['id'],current)
                    self.q.db.transaction(remember)
                    self.sync_one(item['id'])
                    break

    def hold(self,item,reason):
        self.q.hold(item['id'],'Preflight failed; review the Notion record')
        page=self.q.db.get('lead_'+item['lead_id'])['data']['notion_page_id']
        current=self.notion.request('pages/'+page,'GET')
        if current.get('archived') or current.get('in_trash'):return
        status=(current.get('properties',{}).get('STATUS',{}).get('status') or {}).get('name')
        props={'Delivery State':{'rich_text':rich('Held: '+reason[:400])}}
        if status not in delivery.STOP|{'Sent','Sending'}:props['STATUS']={'status':{'name':'Needs Review'}}
        self.notion.request('pages/'+page,'PATCH',{'properties':props})
        def reset_done(tx):
            held=tx.get('outbox_'+item['id']);held['approval_reset_done']=True;tx.put('outbox_'+item['id'],held)
        self.q.db.transaction(reset_done)

    def tick(self, timestamp=None):
        now = time.time() if timestamp is None else timestamp
        cfg = self.s['sending']
        if cfg['mode'] != 'automatic' or self.q.control()['paused']:
            return {'state': 'paused-or-draft-only'}
        self.report('gmail_identity')
        if self.gmail.identity() != cfg['sender'].lower(): raise ValueError('Wrong Gmail sender')
        self.sync_leads()
        self.report('receipt_sync')
        for saved in self.q.db.list('outbox'):
            if saved['state']=='sent' and saved.get('mode')!='test' and self.sync_one(saved['id']) is False:
                return {'state':'notion-sync-pending'}
        self.report('reply_check')
        self.poll()
        if self.q.control().get('active_attempt'): raise ValueError('Reconcile unresolved send first')
        if any(saved.get('notion_sync_pending') for saved in self.q.db.list('outbox') if saved['state']=='sent' and saved.get('mode')!='test'):
            return {'state':'notion-sync-pending'}
        for item in sorted(self.q.db.list('outbox'), key=lambda x: x.get('due_at', 0)):
            if item['state'] != 'queued' or item.get('mode') == 'test' or item['due_at'] > now: continue
            with tempfile.TemporaryDirectory() as folder:
                store = self.local(folder)
                self.report('preflight')
                try: lead = self.preflight(item, store)
                except ValueError as exc:
                    self.hold(item,str(exc))
                    continue
                finally: store.db.close()
            clock = datetime.fromtimestamp(now, timezone.utc)
            if not permitted_time(cfg, clock, lead): continue
            try:
                self.report('source_and_history_check')
                delivery.recheck(lead, self.s['preferences'], self.research)
                if self.gmail.prior_contact(item['recipient']):raise ValueError('Gmail already contains contact with this recipient')
                if self.gmail.prior_company_contact(item['company']):raise ValueError('Gmail may already contain contact with this company; review history')
            except ValueError as exc:
                self.hold(item,str(exc));continue
            # Refresh time after network work; never dispatch using a stale 10:59 check.
            with tempfile.TemporaryDirectory() as folder:
                store=self.local(folder)
                try:lead=self.preflight(item,store)
                except ValueError as exc:
                    self.hold(item,str(exc));continue
                finally:store.db.close()
            dispatch = time.time() if timestamp is None else timestamp
            if not permitted_time(cfg, datetime.fromtimestamp(dispatch, timezone.utc), lead): continue
            control=self.q.control();plan=self.q.db.get('campaign_'+item['campaign'])
            day=datetime.fromtimestamp(dispatch,timezone.utc).astimezone(ZoneInfo(cfg['timezone'])).date().isoformat()
            if not plan or datetime.fromtimestamp(dispatch,timezone.utc).astimezone(ZoneInfo(item['company_timezone'])).date().isoformat() not in plan['dates']:continue
            if plan['sent_attempts']>=plan['maximum_sends'] or control.get('days',{}).get(day,0)>=cfg['daily_limit']:continue
            if control.get('last_attempt',0) and dispatch-control['last_attempt']<cfg['minimum_interval_seconds']:continue
            self.report('durable_claim')
            self.q.claim(item['id'], dispatch, settings_hash(self.s), cfg['daily_limit'],
                         cfg['minimum_interval_seconds'], cfg['timezone'])
            # From this point every crash is a durable unresolved send, never a retry.
            try:
                if hasattr(self.q.db,'assert_current'):self.q.db.assert_current()
                if self.q.control()['paused']: raise ValueError('Paused immediately before dispatch')
                self.report('gmail_dispatch')
                result = self.gmail.send(cfg['sender'], item['recipient'], item['subject'], item['body'], item['message_id'])
                self.report('receipt_persistence')
                self.q.outcome(item['id'], result)
            except Exception:
                # Do not log exception bodies: they may contain tokens or message content.
                self.q.outcome(item['id'], error='Dispatch or receipt persistence failed')
                raise
            self.report('receipt_reference')
            try:
                message=self.gmail.message(result['id'])
                if not isinstance(message,dict):raise ValueError('Receipt metadata unavailable')
                h={v['name'].lower():v['value'] for v in message.get('payload',{}).get('headers',[])}
                if message.get('id')==result['id'] and h.get('message-id'):
                    def save_reference(tx):
                        saved=tx.get('outbox_'+item['id']);saved['provider_message_id']=h['message-id'];tx.put('outbox_'+item['id'],saved)
                    self.q.db.transaction(save_reference)
            except StateError:raise
            except (ValueError,TypeError,KeyError):pass
            self.report('notion_receipt_sync')
            synced=self.sync_one(item['id'])
            return {'state': 'sent', 'id': item['id'], 'notion_sync_pending':not synced}
        # Repair Notion independently; receipt was committed before Notion update.
        for item in self.q.db.list('outbox'):
            if item['state'] == 'sent' and item.get('mode') != 'test': self.sync_one(item['id'])
        return {'state': 'no-due-send'}

    def sync_one(self, key):
        """Retry only Notion after a saved receipt; never repeat Gmail dispatch.

        Provider failure is a visible pending sync, not a failed email. Durable
        state errors still stop the worker; they must never be swallowed.
        """
        item=self.q.db.get('outbox_'+key)
        if item['state']!='sent' or item.get('mode')=='test':return True
        fingerprint=digest([item['gmail_id'],item['thread_id'],item['attempted_at'],item.get('reply_reason','')])
        if (item.get('notion_receipt_synced')==fingerprint and not item.get('notion_sync_pending')
                and time.time()-item.get('notion_synced_at',0)<15*60):return True
        try:
            visible=self._sync_one(key)
        except StateError:raise
        except (ValueError,KeyError,TypeError) as exc:
            from .health import safe_error
            def pending(tx):
                saved=tx.get('outbox_'+key)
                saved.update(notion_sync_pending=True,notion_sync_error=safe_error(exc))
                tx.put('outbox_'+key,saved)
            self.q.db.transaction(pending)
            return False
        def synced(tx):
            saved=tx.get('outbox_'+key)
            saved.update(notion_sync_pending=False,notion_sync_error=None,
                         notion_receipt_synced=fingerprint,notion_synced_at=time.time(),
                         notion_sync_state='synced' if visible else 'archived')
            tx.put('outbox_'+key,saved)
        self.q.db.transaction(synced)
        return True

    def _sync_one(self, key):
        item = self.q.db.get('outbox_' + key)
        if item['state'] != 'sent' or item.get('mode') == 'test': return
        lead = self.q.db.get('lead_' + item['lead_id'])['data']
        current=self.notion.request('pages/'+lead['notion_page_id'],'GET')
        if current.get('archived') or current.get('in_trash'):return False
        current_status=(current.get('properties',{}).get('STATUS',{}).get('status') or {}).get('name','')
        preserve=current_status in ('Replied','Interview','Won','Closed','Rejected','Do Not Contact')
        self.notion.request('pages/' + lead['notion_page_id'], 'PATCH', {'properties': {
            **({} if preserve else {'STATUS': {'status': {'name': ('Do Not Contact' if any(w in item.get('reply_reason','') for w in ('Opt-out','Bounce')) else 'Replied') if item.get('reply_reason') else 'Sent'}}}),
            **({'Reply Status': {'rich_text': rich(item['reply_reason'])}} if item.get('reply_reason') else {}), 'Delivery State': {'rich_text': rich('sent')},
            'Gmail Message ID': {'rich_text': rich(item['gmail_id'])},
            'Gmail Thread ID': {'rich_text': rich(item['thread_id'])},
            'sent time': {'date': {'start': datetime.fromtimestamp(item['attempted_at'], timezone.utc).isoformat()}}}})
        return True

    def reconcile(self, key):
        item = self.q.db.get('outbox_' + key)
        if item['state'] not in ('sending', 'uncertain'): raise ValueError('No unresolved send')
        found = self.gmail.find_sent(item['message_id'])
        if not found: raise ValueError('No receipt found; absence is NOT permission to retry')
        message = self.gmail.message(found['id'])
        headers = {h['name'].lower(): h['value'] for h in message['payload']['headers']}
        if ('SENT' not in message.get('labelIds', []) or headers.get('message-id') != item['message_id'] or
            parseaddr(headers.get('from', ''))[1].lower() != self.s['sending']['sender'].lower() or
            {a.lower() for _, a in getaddresses([headers.get('to', '')])} != {item['recipient'].lower()}):
            raise ValueError('Receipt identity mismatch')
        self.q.outcome(key, {'id': message['id'], 'threadId': message['threadId']})
        self.sync_one(key)
        return {'state': 'sent', 'id': key}
