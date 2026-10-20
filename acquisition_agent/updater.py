"""Local release installer. Preserves credentials, state and user settings."""
import fcntl
import json
import os
import shutil
import sys
from datetime import datetime,timezone
from pathlib import Path


def manifest(root):
    from .delivery import policy
    from .discovery import source_config
    read=lambda name:json.loads((root/'config'/name).read_text())
    return policy(read('sending.json'),read('profile.json'),source_config(read('preferences.json'),root),read('exclusions.json'))



def install(source,target):
    source,target=Path(source).resolve(),Path(target).expanduser().resolve()
    if source==target:raise ValueError('Choose your existing installation, not this extracted release')
    if not (target/'config/profile.json').is_file() or not (target/'acquisition_agent/__main__.py').is_file():
        raise ValueError('Target is not an existing Shine agent installation')
    if not (source/'acquisition_agent/panel_assets/app.js').is_file():raise ValueError('Release is incomplete')
    state=target/'state';state.mkdir(exist_ok=True)
    locks=[]
    try:
        for name in ('agent.lock','worker.lock','panel.lock','delivery.lock','automatic-research.lock'):
            handle=(state/name).open('a');locks.append(handle)
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Stop the running panel and workers with Ctrl+C before updating') from None
        from .delivery import fingerprint
        approval=state/'sending-approval.json';evidence=state/'test-evidence.json'
        try:
            carry_approval=approval.exists() and evidence.exists() and json.loads(evidence.read_text()).get('reply_verified') and json.loads(approval.read_text()).get('sha256')==fingerprint(manifest(target))
        except (ValueError,KeyError,OSError):carry_approval=False
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=target/'update-backups'/stamp;backup.mkdir(parents=True,mode=0o700)
        # Snapshot only files this installer can change. Never copy mailbox tokens.
        for name in ('acquisition_agent','tests','docs','examples','Start-Agent.command','Run-Shine.command','Configure-Automatic-Research.command','README.md','Connect-Outreach.command','config/notion_connection.json','config/discovery.json','config/preferences.json','config/sending.json','config/profile.json','state/sending-approval.json'):
            path=target/name
            if path.is_dir():shutil.copytree(path,backup/name,ignore=shutil.ignore_patterns('__pycache__'))
            elif path.exists():
                (backup/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup/name)
        for name in ('acquisition_agent','tests','docs','examples'):
            shutil.copytree(source/name,target/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('Start-Agent.command','Run-Shine.command','Configure-Automatic-Research.command','Connect-Outreach.command','README.md'):
            if (source/name).exists():shutil.copy2(source/name,target/name)
        for name in ('sending.json','discovery.json'):
            path=target/'config'/name
            if not path.exists():shutil.copy2(source/'config'/name,path)
        # Migrate only the known failed Remotive URL, retaining all user watchlists.
        path=target/'config/discovery.json';value=json.loads(path.read_text())
        feeds=value.get('rss_feeds',[])
        if 'https://remotive.com/feed' in feeds:
            value['rss_feeds']=list(dict.fromkeys([u for u in feeds if u!='https://remotive.com/feed']+['https://remotive.com/remote-jobs/feed/design','https://remotive.com/remote-jobs/feed/marketing']))
            temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');os.replace(temp,path)
        # Add the requested Dubai market without replacing any user preferences.
        path=target/'config/preferences.json';preferences=json.loads(path.read_text())
        changed=False
        for key in ('countries','search_markets'):
            if key in preferences and isinstance(preferences[key],list) and 'United Arab Emirates' not in preferences[key]:
                preferences[key].append('United Arab Emirates');changed=True
        if changed:
            temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(preferences,indent=2)+'\n');os.replace(temp,path)
        migration=state/'migrations/v0.13-policy.json'
        if not migration.exists():
            from .signature import SIGNATURE
            path=target/'config/sending.json';config=json.loads(path.read_text())
            config.update(daily_limit=50,minimum_interval_seconds=180,send_hours=[8,11],send_weekdays=[0,1,2,3,4],schedule_basis='company',campaign_required=True)
            temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(config,indent=2)+'\n');os.replace(temp,path)
            path=target/'config/profile.json';profile=json.loads(path.read_text());profile['email_signature']=SIGNATURE
            temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(profile,indent=2,ensure_ascii=False)+'\n');os.replace(temp,path)
            # Carry only an already valid, live-tested policy approval, within the owner's explicit update request.
            if carry_approval and not changed:
                updated={'sha256':fingerprint(manifest(target)),'approved_at':datetime.now(timezone.utc).isoformat(),'sender':profile['sender_email'],'basis':'Owner requested 50/day maximum, explicit campaign targets, company-local 08–11 weekdays and exact Shine WhatsApp closing.'}
                temp=approval.with_suffix('.json.tmp');temp.write_text(json.dumps(updated,indent=2)+'\n');os.chmod(temp,0o600);os.replace(temp,approval)
            migration.parent.mkdir(exist_ok=True);migration.write_text(json.dumps({'version':'0.13.0','applied_at':datetime.now(timezone.utc).isoformat(),'approval_carried':bool(carry_approval and not changed)})+'\n')
        print('Applied 50/day ceiling, 08–11 company-local weekdays, three-minute spacing and signature. Campaign target required; no campaign is started by this updater.')
        print('Updated code and the requested sending settings/signature. Existing sending mode, other profile/settings, credentials and state preserved.')
        if changed:print('UAE added to targeting. Review sending-plan and approve the changed policy before automatic sending can resume.')
        # Requested destination switch is verified before settings change. A missing
        # Notion grant leaves the existing installation connected as before.
        if not (target/'config/notion_connection.json').exists():
            from .connect_outreach import connect
            try:connect(target,already_locked=True)
            except (ValueError,OSError) as exc:print('Original Outreach connection pending: '+str(exc))
        links=source/'config/outreach-migration-links.json'
        if links.exists() and (target/'config/notion_connection.json').exists():
            from .rebind_outreach import apply
            result=apply(target,links,backup/'outreach-links')
            print('Original Outreach record links: '+json.dumps(result))
        print('Code/config rollback copy: '+str(backup))
        return backup
    finally:
        for handle in reversed(locks):handle.close()


if __name__=='__main__':
    try:
        if len(sys.argv)!=3:raise ValueError('Usage: python3 -m acquisition_agent.updater RELEASE_FOLDER EXISTING_FOLDER')
        install(sys.argv[1],sys.argv[2])
    except (OSError,ValueError) as exc:
        print('Update stopped: '+str(exc));raise SystemExit(1)
