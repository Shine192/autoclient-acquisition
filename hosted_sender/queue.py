"""Firestore state machine. Never put external side effects in transactions."""
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Queue:
    def __init__(self, db):
        self.db = db

    def control(self):
        return self.db.get('control') or {'paused': True, 'migration_complete': False}

    def init(self):
        def op(tx):
            if tx.get('control'):
                raise ValueError('Already initialized; refusing to reset sending history')
            tx.put('control', {'kind': 'control', 'paused': True, 'migration_complete': False,
                               'active_attempt': '', 'last_attempt': 0, 'days': {}})
        self.db.transaction(op)

    def put_new(self, key, value):
        def op(tx):
            if tx.get(key):
                raise ValueError('Record already exists')
            tx.put(key, value)
        self.db.transaction(op)

    def pause(self, value=True):
        def op(tx):
            c = tx.get('control')
            if not c: raise ValueError('Initialize cloud state first')
            c['paused'] = value
            tx.put('control', c)
        self.db.transaction(op)

    def campaign(self, key, value):
        # Immutable campaign records: changed dates/targeting need a new approval.
        datetime.fromisoformat(value['start_date']); datetime.fromisoformat(value['end_date'])
        if value['end_date'] < value['start_date'] or not value['dates']:
            raise ValueError('Select explicit campaign dates')
        if not 1 <= value['maximum_sends'] <= 100:
            raise ValueError('Pilot campaign cap is 1–100')
        for day in value['dates']:
            date = datetime.fromisoformat(day).date()
            if date.weekday() >= 5 or not value['start_date'] <= day <= value['end_date']:
                raise ValueError('Send dates must be weekdays inside the campaign')
        self.put_new('campaign_' + key, dict(value, kind='campaign', id=key, sent_attempts=0))

    def enqueue(self, item):
        if item.get('stage', 0) != 0:
            raise ValueError('Cloud pilot follow-ups are disabled')
        key = item['id']
        refs = ['recipient_' + digest(item['recipient'].lower()), 'company_' + digest(item['company'].lower())]
        def op(tx):
            # All reads precede writes (Firestore requirement).
            existing = tx.get('outbox_' + key)
            reservations = [tx.get(k) for k in refs]
            if existing:
                if existing['state']=='blocked' and not existing.get('attempted_at') and existing.get('approval_reset_done'):
                    if any(r and r.get('outbox_id')!=key for r in reservations):raise ValueError('Company or recipient already reserved/contacted')
                    replacement=dict(item,kind='outbox',state='queued',attempted_at=None)
                    tx.put('outbox_'+key,replacement)
                    for ref in refs:tx.put(ref,{'kind':'dedup','outbox_id':key})
                    return replacement
                return existing
            if any(reservations): raise ValueError('Company or recipient already reserved/contacted')
            tx.put('outbox_' + key, dict(item, kind='outbox', state='queued', attempted_at=None))
            for ref in refs: tx.put(ref, {'kind': 'dedup', 'outbox_id': key})
            return dict(item, state='queued')
        return self.db.transaction(op)

    def claim(self, key, timestamp, settings_hash, daily_limit, interval, timezone_name):
        if type(daily_limit) is not int or not 1<=daily_limit<=50 or interval<180:
            raise ValueError('Maximum 50/day and at least three minutes between messages')
        day = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo(timezone_name)).date().isoformat()
        def op(tx):
            c, item = tx.get('control'), tx.get('outbox_' + key)
            if not item: raise ValueError('Unknown queue item')
            campaign = tx.get('campaign_' + item['campaign'])
            domains = [item['company'], item['recipient'].split('@')[-1]]
            suppression_values = {item['recipient'].lower()}
            for domain in domains:
                parts=domain.lower().split('.')
                suppression_values.update('.'.join(parts[i:]) for i in range(max(1,len(parts)-1)))
            suppressions = [tx.get('suppress_' + digest(v)) for v in sorted(suppression_values)]
            if not c or c['paused'] or not c['migration_complete']: raise ValueError('Paused or migration incomplete')
            if 'active_campaign' in c and c['active_campaign']!=item['campaign']:raise ValueError('Campaign is not active')
            if item['state'] != 'queued': raise ValueError('Already attempted or blocked')
            if c.get('active_attempt'): raise ValueError('Unresolved send blocks all new sends')
            if c.get('approved_hash') != settings_hash or not c.get('test_verified'):
                raise ValueError('Cloud policy and live self-inbox/reply test need approval')
            if not campaign or campaign['settings_hash'] != settings_hash: raise ValueError('Campaign policy changed')
            local_day = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo(item['company_timezone'])).date().isoformat()
            if local_day not in campaign['dates']: raise ValueError('Not a selected campaign date')
            if campaign['sent_attempts'] >= campaign['maximum_sends']: raise ValueError('Campaign cap reached')
            if any(suppressions): raise ValueError('Suppressed')
            if timestamp < item['due_at']: raise ValueError('Not due')
            if c.get('days', {}).get(day, 0) >= daily_limit: raise ValueError('Daily cap reached')
            if c.get('last_attempt', 0) and timestamp - c['last_attempt'] < interval: raise ValueError('Wait for sending interval')
            c['active_attempt'] = key
            c['last_attempt'] = timestamp
            c.setdefault('days', {})[day] = c.get('days', {}).get(day, 0) + 1
            # Keep a bounded accounting window; no delivery identities are deleted.
            c['days'] = dict(sorted(c['days'].items())[-90:])
            campaign['sent_attempts'] += 1
            item.update(state='sending', attempted_at=timestamp)
            tx.put('control', c); tx.put('campaign_' + item['campaign'], campaign); tx.put('outbox_' + key, item)
            return item
        return self.db.transaction(op)

    def outcome(self, key, result=None, error=''):
        def op(tx):
            c, item = tx.get('control'), tx.get('outbox_' + key)
            if c.get('active_attempt') != key or item['state'] not in ('sending', 'uncertain'):
                raise ValueError('Attempt ownership mismatch')
            if result and result.get('id') and result.get('threadId'):
                item.update(state='sent', gmail_id=result['id'], thread_id=result['threadId'], error='')
                c['active_attempt'] = ''
            else:
                item.update(state='uncertain', error='Outcome unknown; reconcile Gmail receipt. ' + error[:120])
            tx.put('outbox_' + key, item); tx.put('control', c)
        self.db.transaction(op)

    def hold(self,key,reason):
        def op(tx):
            item=tx.get('outbox_'+key)
            if not item or item['state']!='queued' or item.get('attempted_at'):raise ValueError('Only unattempted items can be held')
            item.update(state='blocked',error=reason[:500]);tx.put('outbox_'+key,item)
        self.db.transaction(op)

    def suppress(self, values, reason):
        def op(tx):
            for value in values:
                tx.put('suppress_' + digest(value.lower()), {'kind': 'suppression', 'value': value.lower(), 'reason': reason})
        self.db.transaction(op)
