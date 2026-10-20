"""Durable, explicit campaign totals. A restart or midnight never resets a target."""
import json
import uuid
from .core import now


def init(store):
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, target INTEGER NOT NULL,
      status TEXT NOT NULL, created_at TEXT NOT NULL, closed_at TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS one_active_campaign ON campaigns(status) WHERE status='active';
    CREATE TABLE IF NOT EXISTS campaign_attempts(outbox_id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL, attempted_at TEXT NOT NULL);
    ''')
    store.db.commit()


def active(store):
    init(store)
    row=store.db.execute("SELECT id,target,status,created_at FROM campaigns WHERE status='active'").fetchone()
    if not row:return None
    value=dict(zip(('id','target','status','created_at'),row))
    value['attempted']=store.db.execute('SELECT COUNT(*) FROM campaign_attempts WHERE campaign_id=?',(row[0],)).fetchone()[0]
    value['remaining']=max(0,value['target']-value['attempted'])
    value['sent']=store.db.execute("SELECT COUNT(*) FROM outbox WHERE campaign_id=? AND state='sent'",(row[0],)).fetchone()[0]
    value['queued']=store.db.execute("SELECT COUNT(*) FROM outbox WHERE campaign_id=? AND state='queued'",(row[0],)).fetchone()[0]
    value['uncertain']=store.db.execute("SELECT COUNT(*) FROM outbox WHERE campaign_id=? AND state IN ('sending','uncertain')",(row[0],)).fetchone()[0]
    return value


def configure(store,action,target=None):
    # UI/CLI calls serialize with Gmail sending and queue association.
    from .delivery import lock
    with lock(store):
        current=active(store)
        if action in ('start','update'):
            if type(target) is not int or not 1<=target<=1000:raise ValueError('Campaign target must be a whole number from 1 to 1000')
            if action=='start':
                if current:raise ValueError('A campaign is already active. Update its target or close it first.')
                store.db.execute('INSERT INTO campaigns VALUES(?,?,?,?,NULL)',(uuid.uuid4().hex,target,'active',now()))
            else:
                if not current:raise ValueError('No active campaign to update')
                if target<current['attempted']:raise ValueError('Target cannot be below attempts already reserved, including uncertain sends')
                store.db.execute('UPDATE campaigns SET target=? WHERE id=?',(target,current['id']))
            store.db.commit()
            return {'campaign':active(store),'message':'Campaign target saved. Sending still follows mode, approval, daily limit and company-local windows.'}
        if action=='close':
            if not current:raise ValueError('No active campaign')
            if current['uncertain']:raise ValueError('Reconcile uncertain sending outcomes before closing this campaign')
            cancelled=store.db.execute("UPDATE outbox SET state='cancelled',error='Campaign closed by owner; no send attempted' WHERE campaign_id=? AND attempted_at IS NULL AND state IN ('queued','blocked')",(current['id'],)).rowcount
            store.db.execute("UPDATE campaigns SET status='closed',closed_at=? WHERE id=?",(now(),current['id']));store.db.commit()
            return {'campaign':None,'message':'Campaign closed; '+str(cancelled)+' unsent queue items cancelled. Sending history preserved.'}
        raise ValueError('Choose start, update or close')


def assignment(store,config):
    if config['mode']!='automatic' or not config.get('campaign_required'):return ''
    current=active(store)
    if not current:raise ValueError('Choose a campaign target in Delivery queue before automatic queueing')
    if not current['remaining']:raise ValueError('Campaign target reached; no new applications queued')
    return current['id']


def permitted(store,item):
    current=active(store)
    return bool(current and item.get('campaign_id')==current['id'] and current['remaining']>0)


def claim(store,item,stamp):
    """Atomically reserve one campaign attempt AND mark the exact outbox row sending."""
    init(store)
    try:
        store.db.execute('BEGIN IMMEDIATE')
        campaign=store.db.execute("SELECT target FROM campaigns WHERE id=? AND status='active'",(item.get('campaign_id',''),)).fetchone()
        if not campaign:raise ValueError('Queued message has no active campaign; no send attempted')
        count=store.db.execute('SELECT COUNT(*) FROM campaign_attempts WHERE campaign_id=?',(item['campaign_id'],)).fetchone()[0]
        if count>=campaign[0]:raise ValueError('Campaign target reached')
        updated=store.db.execute("UPDATE outbox SET state='sending',attempted_at=? WHERE id=? AND state='queued' AND attempted_at IS NULL AND campaign_id=?",(stamp,item['id'],item['campaign_id'])).rowcount
        if updated!=1:raise ValueError('Outbox item is no longer eligible for a new attempt')
        store.db.execute('INSERT INTO campaign_attempts VALUES(?,?,?)',(item['id'],item['campaign_id'],stamp))
        store.db.execute('INSERT INTO delivery_events(outbox_id,event,detail,at) VALUES(?,?,?,?)',(item['id'],'sending','Campaign allowance reserved before Gmail request',stamp))
        store.db.commit()
    except Exception:
        store.db.rollback();raise
