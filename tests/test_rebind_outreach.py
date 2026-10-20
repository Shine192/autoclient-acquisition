import json,sqlite3,tempfile,unittest
from pathlib import Path
from acquisition_agent.rebind_outreach import apply
from acquisition_agent.notion_compat import SOURCE

class RebindTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  (self.root/'state').mkdir();(self.root/'config').mkdir()
  (self.root/'config/preferences.json').write_text(json.dumps({'notion_leads_source_id':SOURCE}))
  self.row={'lead_id':'a'*16,'old_page_id':'11111111-1111-4111-8111-111111111111','new_page_id':'22222222-2222-4222-8222-222222222222'}
  self.lead={'id':'a'*16,'notion_page_id':self.row['old_page_id'],'status':'Sent','draft':{'subject':'Owner edited','body':'Keep my exact body'},'gmail_message_id':'sent-proof','approved':False}
  db=self.db();db.executescript('CREATE TABLE leads(id TEXT PRIMARY KEY,data TEXT);CREATE TABLE outbox(id TEXT,state TEXT);CREATE TABLE campaigns(id TEXT,target INTEGER);')
  db.execute('INSERT INTO leads VALUES(?,?)',(self.lead['id'],json.dumps(self.lead)));db.execute("INSERT INTO outbox VALUES('queue','sent')");db.execute("INSERT INTO campaigns VALUES('campaign',12)");db.commit();db.close()
  self.file=self.root/'links.json';self.write([self.row])
 def db(self):return sqlite3.connect(str(self.root/'state/agent.sqlite3'))
 def write(self,rows):self.file.write_text(json.dumps({'target_id':SOURCE,'records':rows}))
 def test_only_link_changes_and_sent_history_remains(self):
  result=apply(self.root,self.file,self.root/'backup');db=self.db()
  lead=json.loads(db.execute('SELECT data FROM leads').fetchone()[0]);self.assertEqual(lead,dict(self.lead,notion_page_id=self.row['new_page_id'],previous_notion_page_id=self.row['old_page_id']))
  self.assertEqual(db.execute('SELECT * FROM outbox').fetchall(),[('queue','sent')]);self.assertEqual(db.execute('SELECT * FROM campaigns').fetchall(),[('campaign',12)]);db.close()
  self.assertEqual(result['relinked'],1);self.assertTrue((self.root/'backup/agent-before-outreach-links.sqlite3').exists())
 def test_retry_is_idempotent(self):
  apply(self.root,self.file,self.root/'backup');result=apply(self.root,self.file,self.root/'backup2');self.assertEqual(result['relinked'],0);self.assertEqual(result['already_linked'],1)
 def test_changed_link_fails_before_any_update(self):
  self.write([dict(self.row,old_page_id='33333333-3333-4333-8333-333333333333')])
  with self.assertRaisesRegex(ValueError,'changed'):apply(self.root,self.file,self.root/'backup')
  db=self.db();self.assertEqual(json.loads(db.execute('SELECT data FROM leads').fetchone()[0]),self.lead);db.close()
 def test_duplicate_destination_rejected(self):
  self.write([self.row,dict(self.row,lead_id='b'*16)])
  with self.assertRaisesRegex(ValueError,'Repeated destination'):apply(self.root,self.file,self.root/'backup')
 def test_wrong_destination_and_missing_history_fail_closed(self):
  self.file.write_text(json.dumps({'target_id':'wrong','records':[self.row]}))
  with self.assertRaisesRegex(ValueError,'destination'):apply(self.root,self.file,self.root/'backup')
  self.write([self.row]);(self.root/'state/agent.sqlite3').unlink()
  with self.assertRaisesRegex(ValueError,'history'):apply(self.root,self.file,self.root/'backup')

class LinkCommandTests(RebindTests):
 def locks(self):
  for name in ('worker.lock','panel.lock','delivery.lock','automatic-research.lock'):(self.root/'state'/name).touch()
 def run_command(self):
  import subprocess,sys
  return subprocess.run([sys.executable,'-m','acquisition_agent.rebind_outreach',str(self.root),str(self.file)],cwd=str(Path(__file__).resolve().parent.parent),capture_output=True,text=True)
 def test_cli_links_existing_installation_under_exclusive_locks(self):
  self.locks();r=self.run_command();self.assertEqual(r.returncode,0,r.stdout+r.stderr)
  db=self.db();self.assertEqual(json.loads(db.execute('SELECT data FROM leads').fetchone()[0])['notion_page_id'],self.row['new_page_id']);db.close()
 def test_cli_refuses_active_worker_without_changing_record(self):
  import fcntl
  self.locks()
  with (self.root/'state/worker.lock').open('r') as h:
   fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB);r=self.run_command()
  self.assertEqual(r.returncode,1);self.assertIn('worker.lock',r.stdout)
  db=self.db();self.assertEqual(json.loads(db.execute('SELECT data FROM leads').fetchone()[0]),self.lead);db.close()
 def test_cli_refuses_uncertain_delivery(self):
  self.locks();db=self.db();db.execute("UPDATE outbox SET state='uncertain'");db.commit();db.close()
  r=self.run_command();self.assertEqual(r.returncode,1);self.assertIn('uncertain',r.stdout)
