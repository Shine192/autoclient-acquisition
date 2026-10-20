"""Explicit hosted operations. Scheduled runs never initialize or reset history."""
import argparse,json,os,secrets,sys,tempfile,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from .github_state import API,GitHubState,StateError
from .queue import Queue
from .worker import Worker,settings_hash
from .notion_import import refresh
from acquisition_agent.gmail import Gmail,private_json
from acquisition_agent.providers import Notion
from acquisition_agent.delivery import message_text

REPOSITORY='Shine192/autoclient-acquisition'

def gmail(folder):
    token={name:os.environ['GMAIL_'+name.upper()] for name in ('client_id','client_secret','refresh_token')}
    token.update(expires_at=0)
    path=Path(folder)/'gmail.json';private_json(path,token)
    return Gmail(path)

def policy_summary(settings):
    cfg=settings['sending']
    return {'policy_hash':settings_hash(settings),'sender':'Configured Shine Gmail account; verify locally in policy-review.json',
            'daily_limit':cfg['daily_limit'],'company_local_hours':cfg['send_hours'],
            'weekdays':cfg['send_weekdays'],'minimum_interval_seconds':cfg['minimum_interval_seconds'],
            'minimum_fit_score':cfg['minimum_fit_score'],'offers':[k for k,v in cfg['offers'].items() if v['enabled']],
            'followups':'disabled','approval':'Notion STATUS = Approve','history':'Encrypted persistent Git branch'}

def self_test(q,s,g):
    sender=s['sending']['sender'].lower()
    if g.identity()!=sender:raise ValueError('Wrong Gmail identity')
    key='test-'+secrets.token_hex(12);nonce='SHINE-GITHUB-VERIFY '+secrets.token_hex(16)
    item={'kind':'outbox','id':key,'mode':'test','state':'sending','recipient':sender,'company':'self-test',
          'attempted_at':time.time(),'message_id':'<'+key+'@gmail.com>','test_nonce':nonce,'settings_hash':settings_hash(s)}
    def claim(tx):
        c=tx.get('control')
        if c.get('active_attempt'):raise ValueError('Resolve the outstanding send first')
        c['active_attempt']=key;tx.put('outbox_'+key,item);tx.put('control',c)
    q.db.transaction(claim)
    try:
        receipt=g.send(sender,sender,'Shine GitHub sender test','Reply to this email with this exact line:\n'+nonce+'\n\n'+s['profile']['portfolio_url'],item['message_id'])
        q.outcome(key,receipt)
    except Exception:
        q.outcome(key,error='Self-test outcome unknown');raise
    return {'test_id':key,'next':'Reply in Gmail with the verification line, then use verify-test with this ID'}

def verify_test(q,s,g,key):
    from email.utils import parseaddr
    item=q.db.get('outbox_'+key)
    if not item or item.get('mode')!='test' or item['state']!='sent' or item['settings_hash']!=settings_hash(s):raise ValueError('Need a successful test under current policy')
    sender=s['sending']['sender'].lower();found=[]
    for m in g.thread(item['thread_id']):
        headers={x['name'].lower():x['value'] for x in m.get('payload',{}).get('headers',[])}
        if m['id']!=item['gmail_id'] and 'DRAFT' not in m.get('labelIds',[]) and int(m.get('internalDate','0'))>=item['attempted_at']*1000 and parseaddr(headers.get('from',''))[1].lower()==sender and item['test_nonce'] in message_text(m):found.append(m['id'])
    if not found:raise ValueError('Self-inbox reply not found')
    def save(tx):
        c=tx.get('control');c.update(test_verified=True,test_hash=settings_hash(s),test_receipt=found[0]);tx.put('control',c)
    q.db.transaction(save)
    return {'reply_verified':True}

def activate(q,s,expected):
    if expected!=settings_hash(s):raise ValueError('Review the current policy hash')
    def op(tx):
        c=tx.get('control')
        if not c.get('mac_sender_disabled') or not c.get('migration_imported'):raise ValueError('Complete the Mac handover first')
        if not c.get('test_verified') or c.get('test_hash')!=expected:raise ValueError('Verify the hosted self-inbox reply first')
        if c.get('active_attempt'):raise ValueError('Resolve uncertain delivery first')
        c.update(migration_complete=True,approved_hash=expected,paused=False);tx.put('control',c)
    q.db.transaction(op)
    return {'activated':True,'campaign_required':True}

def campaign(q,s,target,dates):
    if not dates or len(dates)>14 or len(set(dates))!=len(dates):raise ValueError('Choose 1–14 distinct company-local weekdays')
    c=q.control()
    if c.get('active_campaign'):raise ValueError('Close the existing hosted campaign first')
    key=uuid.uuid4().hex
    q.campaign(key,{'id':key,'dates':sorted(dates),'start_date':min(dates),'end_date':max(dates),'maximum_sends':target,'settings_hash':settings_hash(s),'target':None})
    def set_active(tx):
        c=tx.get('control')
        if c.get('active_campaign'):raise ValueError('Another campaign became active')
        c['active_campaign']=key;tx.put('control',c)
    q.db.transaction(set_active)
    return {'campaign_id':key,'maximum_attempts':target,'company_local_dates':sorted(dates)}

def close(q):
    def op(tx):
        c=tx.get('control')
        if c.get('active_attempt'):raise ValueError('Resolve uncertain delivery first')
        active=c.get('active_campaign')
        for item in q.db.list('outbox'):
            if item.get('campaign')==active and item['state'] in ('queued','blocked') and not item.get('attempted_at'):
                item.update(state='cancelled');tx.put('outbox_'+item['id'],item)
        c['active_campaign']=None;tx.put('control',c)
    q.db.transaction(op)
    return {'closed':True,'history_preserved':True}

def run(q,s,g,notion,max_seconds=225):
    if os.getenv('SHINE_DELIVERY_ENABLED')!='true':return {'state':'delivery switch off'}
    c=q.control()
    if c['paused'] or not c.get('migration_complete') or c.get('approved_hash')!=settings_hash(s):return {'state':'paused or setup incomplete'}
    w=Worker(q,s,g,notion)
    if c.get('active_attempt'):return {'state':'uncertain outcome; reconcile before any sending'}
    for item in q.db.list('outbox'):
        if item['state']=='sent' and item.get('mode')!='test':w.sync_one(item['id'])
    active=c.get('active_campaign')
    if not active:
        # Continue bounded reply checks when enabled, even after a campaign is
        # closed. No periodic write is needed merely to remember a poll time.
        # Use a five-minute bucket so timer offsets and short queue delays do
        # not skip reply tracking after the campaign has ended.
        if datetime.now(timezone.utc).minute%15<5:
            if g.identity()!=s['sending']['sender'].lower():raise ValueError('Wrong Gmail sender')
            w.poll()
        return {'state':'no active campaign'}
    plan=q.db.get('campaign_'+active)
    if not plan or plan['sent_attempts']>=plan['maximum_sends']:
        w.poll();return {'state':'campaign target reached'}
    # UTC date can differ from company-local date by one day. Claim still checks
    # the exact company date and weekday immediately before every dispatch.
    today=datetime.now(timezone.utc).date()
    if all(abs((datetime.fromisoformat(d).date()-today).days)>1 for d in plan['dates']):
        # A campaign can end below its target. Keep reply/suppression tracking
        # alive afterwards without importing or sending new applications.
        if datetime.now(timezone.utc).minute%15<5:
            if g.identity()!=s['sending']['sender'].lower():raise ValueError('Wrong Gmail sender')
            w.poll()
        return {'state':'outside campaign dates'}
    summary=refresh(q,notion,s,active)
    started=time.monotonic();sent=0
    for _ in range(2):
        result=w.tick()
        if result['state']!='sent':return {'state':result['state'],'sent_this_run':sent,**summary}
        sent+=1
        # At most two sends per short run; do not sleep if no other candidate can
        # send in this campaign's local window and selected dates.
        candidates=[]
        from acquisition_agent.scheduling import permitted_time
        for item in q.db.list('outbox'):
            if item.get('campaign')!=active or item['state']!='queued':continue
            lead=q.db.get('lead_'+item['lead_id'])['data']
            if permitted_time(s['sending'],datetime.now(timezone.utc),lead):candidates.append(item)
        if not candidates or sent>=2:break
        wait=max(0,s['sending']['minimum_interval_seconds']-(time.time()-q.control()['last_attempt']))
        if time.monotonic()-started+wait+15>max_seconds:break
        time.sleep(wait)
    return {'state':'run complete','sent_this_run':sent,**summary}

def main():
    parser=argparse.ArgumentParser(description='GitHub delivery. No implicit initialization or reset.')
    parser.add_argument('command',nargs='?',default='status',choices=['status','dry-run','self-test','verify-test','activate','pause','resume','campaign','close','run','reconcile'])
    parser.add_argument('--id',default=os.getenv('SHINE_ITEM_ID',''))
    parser.add_argument('--policy-hash',default=os.getenv('SHINE_POLICY_HASH',''))
    parser.add_argument('--target',type=int,default=int(os.getenv('SHINE_CAMPAIGN_TARGET','20') or '20'))
    parser.add_argument('--dates',default=os.getenv('SHINE_CAMPAIGN_DATES',''))
    args=parser.parse_args()
    try:
        db=GitHubState(REPOSITORY,os.environ['SHINE_LEDGER_KEY'],API(REPOSITORY,os.environ['GH_TOKEN']))
        q=Queue(db);s=db.get('settings')['data'];Worker(q,s,None,None)
        if args.command=='status':
            print(json.dumps({'paused':q.control()['paused'],'migration_complete':q.control().get('migration_complete',False),'active_campaign':q.control().get('active_campaign'),'outstanding_attempt':bool(q.control().get('active_attempt')),**policy_summary(s)}));return
        if args.command=='pause':q.pause();print('{"paused":true}');return
        if args.command=='activate':print(json.dumps(activate(q,s,args.policy_hash)));return
        if args.command=='resume':
            c=q.control()
            if not c.get('migration_complete') or c.get('approved_hash')!=settings_hash(s) or c.get('active_attempt'):raise ValueError('Setup or uncertain delivery hold')
            q.pause(False);print('{"paused":false}');return
        if args.command=='campaign':print(json.dumps(campaign(q,s,args.target,[d.strip() for d in args.dates.split(',') if d.strip()])));return
        if args.command=='close':print(json.dumps(close(q)));return
        os.environ['NOTION_TOKEN']=os.environ['NOTION_API_KEY']
        notion=Notion()
        notion.connection={'source_id':s['preferences']['notion_leads_source_id']}
        if args.command=='dry-run':
            pages=list(notion.query(s['preferences']['notion_leads_source_id']))
            print(json.dumps({'notion_rows':len(pages),'approved':sum((p['properties'].get('STATUS',{}).get('status') or {}).get('name')=='Approve' for p in pages),'mutations':False,**policy_summary(s)}));return
        with tempfile.TemporaryDirectory(prefix='shine-github-') as folder:
            g=gmail(folder)
            if args.command=='self-test':result=self_test(q,s,g)
            elif args.command=='verify-test':result=verify_test(q,s,g,args.id)
            elif args.command=='reconcile':result=Worker(q,s,g,notion).reconcile(args.id)
            else:result=run(q,s,g,notion)
            print(json.dumps(result))
    except Exception:
        # Public Actions logs must not contain drafts, contacts, tokens or HTTP bodies.
        print('Operation stopped safely. Check secret names, ledger access, setup status and the Notion hold fields. Never reset history or blindly retry a send.',file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
