"""Connect future research to the owner's original tracker without moving history."""
import fcntl
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from . import notion_compat as compat
from .providers import Notion
from .core import read_json, write_json


def connect(root, notion=None, already_locked=False):
    root=Path(root).resolve();handles=[]
    try:
        if not already_locked:
            for name in ('agent.lock','worker.lock','panel.lock','delivery.lock','automatic-research.lock'):
                handle=(root/'state'/name).open('a');handles.append(handle)
                try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError('Stop Shine with Ctrl+C before connecting the database') from None
        prefpath=root/'config/preferences.json';prefs=read_json(prefpath)
        if prefs.get('notion_leads_source_id') not in ('59935700-60fe-4dea-82c8-eae6806a81b5',compat.SOURCE):
            raise ValueError('A different custom database is configured; no settings changed')
        # Load only the existing Notion credential; never print or copy it.
        env=root/'.env'
        if notion is None:
            if env.exists():
                for line in env.read_text().splitlines():
                    if line.strip().startswith('NOTION_TOKEN='):
                        os.environ.setdefault('NOTION_TOKEN',line.split('=',1)[1].strip().strip('\"\''))
            notion=Notion()
        try:
            properties=notion.request('data_sources/'+compat.SOURCE,'GET')['properties']
            # Boundary translates the original select/status and column names.
            expected={'Name':'title','email SUBJECT':'rich_text','email body':'rich_text','STATUS':'status','COUNTRY':'rich_text','Company Time Zone':'select','EMAIL':'email','WEBSITE':'url'}
            for key,kind in expected.items():
                prop=properties.get(key,{})
                if prop.get('type',next(iter(prop),''))!=kind:
                    raise ValueError('Unexpected original database field: '+key)
            for key in ('Deduplication Key','Research Check','Scheduled Time','Review Summary'):
                if key not in properties:raise ValueError('Original database needs the research fields: '+key)
            records=list(notion.query(compat.SOURCE))
        except Exception as exc:
            raise ValueError('Original Notion access/schema check failed; current connection unchanged. In the original database, add the same Shine Job Acquisition Agent connection used by the Mac, then run Connect-Outreach.command. Details: '+str(exc)[:150]) from None
        from .updater import manifest
        from .delivery import fingerprint
        approval=root/'state/sending-approval.json';evidence=root/'state/test-evidence.json'
        valid=approval.exists() and evidence.exists() and read_json(evidence).get('reply_verified') and read_json(approval).get('sha256')==fingerprint(manifest(root))
        previous=prefs['notion_leads_source_id'];stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=root/'update-backups'/('outreach-'+stamp);backup.mkdir(parents=True,mode=0o700)
        import shutil
        for relative in ('config/preferences.json','config/notion_connection.json','state/sending-approval.json'):
            path=root/relative
            if path.exists():
                (backup/relative).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup/relative)
        connection={'source_id':compat.SOURCE,'database_id':compat.DATABASE,'schema':'original-outreach','verified_at':datetime.now(timezone.utc).isoformat(),'historical_rows_checked':len(records),'old_sender':'GitHub AutoClient Outreach observed Disabled on 2026-10-20','previous_source_id':previous}
        write_json(root/'config/notion_connection.json',connection)
        prefs['notion_leads_source_id']=compat.SOURCE;write_json(prefpath,prefs)
        if valid and previous!=compat.SOURCE:
            write_json(approval,{'sha256':fingerprint(manifest(root)),'approved_at':datetime.now(timezone.utc).isoformat(),'basis':'Owner requested the original Outreach Management System. Only the research destination changed; targeting, offers, sending limits, live-test evidence and individual Notion approval rules preserved.'})
            os.chmod(approval,0o600)
        result={'connected':True,'historical_rows_checked':len(records),'future_research_database':'Outreach Management System','existing_pages_and_outbox':'preserved','policy_approval_preserved':bool(valid),'backup':str(backup)}
        print(json.dumps(result,indent=2));return result
    finally:
        for h in reversed(handles):h.close()


def main():
    root=Path(__file__).resolve().parent.parent
    try:connect(root)
    except (ValueError,OSError) as exc:print('Connection held: '+str(exc));return 1
    print('Open Run-Shine.command. New research goes to your original database; set STATUS to Approve after final review.');return 0

if __name__=='__main__':raise SystemExit(main())
