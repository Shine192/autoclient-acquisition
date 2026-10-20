"""User-run handover. Requires an owner-authorized gh login; never sends email.

This command intentionally is not run by the workspace against the Mac folder.
It preserves the installation and switches only its sender to draft-only.
"""
import argparse,base64,fcntl,json,os,re,shutil,sqlite3,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from cryptography.fernet import Fernet
from .bootstrap import seed
from .github_state import API,initialize
from .cli import REPOSITORY,policy_summary
from .worker import settings_hash

def gh(args,data=None):
    operation='repository API' if args[0]=='api' else ' '.join(args[:2])
    try:result=subprocess.run(['gh',*args],input=data,text=True,capture_output=True,timeout=45)
    except subprocess.TimeoutExpired:raise ValueError('GitHub '+operation+' timed out; setup stopped safely.') from None
    if result.returncode:
        status=re.search(r'HTTP (\d{3})\b',result.stderr or '')
        detail=' (HTTP '+status.group(1)+')' if status else ''
        raise ValueError('GitHub '+operation+' failed'+detail+'. Check connection and access for this operation. Credentials and response bodies are not printed.')
    return result.stdout

def workflow_switch(enabled):
    """Retries are harmless when the previous attempt already paused the timer."""
    def current():
        state=json.loads(gh(['api','repos/'+REPOSITORY+'/actions/workflows/outreach.yml']))['state']
        if state!='active' and not state.startswith('disabled_'):
            raise ValueError('Outreach workflow is unavailable; check its state before handover.')
        return state=='active'
    if current()==enabled:return
    try:gh(['workflow','enable' if enabled else 'disable','outreach.yml','--repo',REPOSITORY])
    except ValueError:
        # Another setup may have reached the desired state after the first read.
        if current()!=enabled:raise
    if current()!=enabled:raise ValueError('Outreach workflow did not reach the requested state; setup stopped.')

def prepare(root):
    root=Path(root).expanduser().resolve();handles=[]
    permissions=json.loads(gh(['api','repos/'+REPOSITORY]))['permissions']
    if not permissions.get('push'):raise ValueError('The GitHub login has no write access. Sign in as the repository owner or add the connected account as a collaborator.')
    current=json.loads(gh(['api','repos/'+REPOSITORY+'/contents/main.py']))
    if 'from hosted_sender.cli import main' not in base64.b64decode(current['content']).decode():raise ValueError('Upload and merge the tested sender update before handover')
    # Stop the obsolete scheduler first; no code/credentials/history is deleted.
    gh(['variable','set','SHINE_DELIVERY_ENABLED','--repo',REPOSITORY,'--body','false'])
    workflow_switch(False)
    backup=root/'update-backups'/('github-handover-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    try:
        for name in ('worker.lock','panel.lock','delivery.lock','automatic-research.lock'):
            handle=(root/'state'/name).open('r');handles.append(handle)
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Close the Shine dashboard and active work, then retry: '+name)
        # Verify all needed credentials exist before changing the local sender.
        credentials=json.loads((root/'state/credentials/gmail-token.json').read_text())
        values={}
        for line in (root/'.env').read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,v=line.split('=',1);values[key.strip()]=v.strip().strip('"').strip("'")
        notion=values.get('NOTION_TOKEN') or values.get('NOTION_API_KEY')
        if not notion or any(not credentials.get(k) for k in ('client_id','client_secret','refresh_token')):raise ValueError('Existing Notion/Gmail authorization is incomplete')
        records=seed(root)  # Reject uncertain local sends before any local write.
        backup.mkdir(parents=True,mode=0o700);backup.chmod(0o700)
        sending=root/'config/sending.json';shutil.copy2(sending,backup/'sending-before-handover.json')
        db=sqlite3.connect((root/'state/agent.sqlite3').as_uri()+'?mode=ro',uri=True)
        snapshot=sqlite3.connect(str(backup/'agent-before-handover.sqlite3'))
        try:db.backup(snapshot)
        finally:db.close();snapshot.close()
        from acquisition_agent.gmail import private_json
        local=json.loads(sending.read_text());local['mode']='draft-only';private_json(sending,local)
        records['control']['mac_sender_disabled']=True
        key=Fernet.generate_key().decode();keyfile=backup/'ledger-key.txt';keyfile.write_text(key+'\n');keyfile.chmod(0o600)
        private_json(backup/'policy-review.json',{'policy':policy_summary(records['settings']['data']),'settings':records['settings']['data']})
        # Values travel on stdin, never in command arguments, logs or source.
        secret_values={'SHINE_LEDGER_KEY':key,'NOTION_API_KEY':notion,
                       **{'GMAIL_'+k.upper():credentials[k] for k in ('client_id','client_secret','refresh_token')}}
        # Ref creation, not replacement: an existing state branch cannot reset.
        token=gh(['auth','token']).strip()
        initialize(REPOSITORY,key,API(REPOSITORY,token),records)
        for name,value in secret_values.items():gh(['secret','set',name,'--repo',REPOSITORY],value)
        workflow_switch(True)
        private_json(backup/'handover-result.json',{'history_imported':True,'mac_sender':'draft-only','hosted_sender':'paused','policy_hash':settings_hash(records['settings']['data'])})
        return {'prepared':True,'mac_sender':'draft-only','hosted_sender':'paused','backup':str(backup),'next':'Run dry-run, self-test, verify-test and activate from GitHub Actions; then choose campaign dates/target and enable the delivery variable.'}
    finally:
        for handle in reversed(handles):handle.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--mac-folder',required=True);args=p.parse_args()
    try:print(json.dumps(prepare(args.mac_folder),indent=2))
    except Exception as exc:
        print('Handover stopped: '+str(exc),file=sys.stderr)
        print('Do not reset an existing delivery-state branch. If local mode changed, leave it draft-only until the hosted state and secrets are checked.',file=sys.stderr)
        raise SystemExit(1)
if __name__=='__main__':main()
