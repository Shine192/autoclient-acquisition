"""Bind a verified copy to existing local lead IDs; never recreate queue history."""
import json,re,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from . import notion_compat


def apply(root, manifest_path, backup):
    """Caller must hold the existing updater worker/panel/delivery locks."""
    root,backup=Path(root),Path(backup)
    manifest=json.loads(Path(manifest_path).read_text())
    prefs=json.loads((root/'config/preferences.json').read_text())
    if manifest.get('target_id')!=notion_compat.SOURCE or prefs.get('notion_leads_source_id')!=notion_compat.SOURCE:
        raise ValueError('Outreach link destination does not match the configured database')
    state=root/'state';db_path=state/'agent.sqlite3'
    if not db_path.exists():raise ValueError('Existing sending history is required; no new database created')
    mappings=manifest.get('records',[])
    if not mappings:raise ValueError('No verified opportunity links supplied')
    ids=set();pages=set()
    for r in mappings:
        if not re.fullmatch(r'[0-9a-f]{16}',r.get('lead_id','')) or r['lead_id'] in ids:raise ValueError('Invalid or repeated lead ID')
        for field in ('old_page_id','new_page_id'):
            if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',r.get(field,'')):raise ValueError('Invalid Notion page ID')
        if r['new_page_id'] in pages:raise ValueError('Repeated destination page')
        ids.add(r['lead_id']);pages.add(r['new_page_id'])
    db=sqlite3.connect(str(db_path));planned=[];unchanged=0;missing=[]
    try:
        # Read and validate every link before the first local mutation.
        for r in mappings:
            row=db.execute('SELECT data FROM leads WHERE id=?',(r['lead_id'],)).fetchone()
            if not row:missing.append(r['lead_id']);continue
            lead=json.loads(row[0]);current=lead.get('notion_page_id')
            if current==r['new_page_id']:unchanged+=1;continue
            if current!=r['old_page_id']:raise ValueError('Opportunity link changed since copy: '+r['lead_id'])
            lead['previous_notion_page_id']=current;lead['notion_page_id']=r['new_page_id']
            planned.append((json.dumps(lead,ensure_ascii=False),r['lead_id']))
        if planned:
            backup.mkdir(parents=True,exist_ok=True)
            snap=sqlite3.connect(str(backup/'agent-before-outreach-links.sqlite3'))
            try:db.backup(snap)
            finally:snap.close()
            db.execute('BEGIN IMMEDIATE')
            try:
                db.executemany('UPDATE leads SET data=? WHERE id=?',planned);db.commit()
            except BaseException:db.rollback();raise
        result={'relinked':len(planned),'already_linked':unchanged,'not_present_locally':missing,'outbox_and_campaigns':'unchanged','at':datetime.now(timezone.utc).isoformat()}
        record=state/'migrations/v0.17.1-outreach-links.json';record.parent.mkdir(exist_ok=True)
        record.write_text(json.dumps(result,indent=2)+'\n')
        return result
    finally:db.close()


def main():
    import fcntl,sys
    if len(sys.argv)!=3:raise ValueError('Usage: rebind_outreach EXISTING_FOLDER VERIFIED_LINK_MANIFEST')
    root=Path(sys.argv[1]).expanduser().resolve();links=Path(sys.argv[2]).resolve();handles=[]
    try:
        # The background agent may be idle: these are the locks protecting its
        # actual sync/research writes and queue/send operations. No code is replaced.
        for name in ('worker.lock','panel.lock','delivery.lock','automatic-research.lock'):
            h=(root/'state'/name).open('r');handles.append(h)
            try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Stop the Shine dashboard and active work before linking: '+name)
        db=sqlite3.connect('file:'+str(root/'state/agent.sqlite3')+'?mode=ro',uri=True)
        try:
            if db.execute("SELECT COUNT(*) FROM outbox WHERE state IN ('sending','uncertain')").fetchone()[0]:
                raise ValueError('Resolve in-progress or uncertain delivery before linking')
        finally:db.close()
        backup=root/'update-backups'/('outreach-links-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        result=apply(root,links,backup);result['backup']=str(backup)
        print(json.dumps(result,indent=2));print('Local Notion links updated. Existing queue, sent history and campaign limits retained. No email sent by this command.')
    finally:
        for h in reversed(handles):h.close()

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,sqlite3.DatabaseError) as exc:
        print('Linking stopped: '+str(exc));raise SystemExit(1)
