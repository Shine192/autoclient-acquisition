import base64,copy,threading,unittest
from cryptography.fernet import Fernet
from hosted_sender.github_state import Codec,GitHubState,StateError,initialize,BRANCH
from hosted_sender.queue import Queue
import test_hosted_queue as fixtures

class FakeGit:
 def __init__(self):self.head=None;self.objects={};self.counter=0;self.lock=threading.Lock();self.fail_before_ref=False;self.fail_after_ref=False
 def __call__(self,path,method='GET',data=None):
  with self.lock:
   def put(v):
    self.counter+=1;key=str(self.counter).zfill(40);self.objects[key]=copy.deepcopy(v);return {'sha':key}
   if path=='git/blobs':return put({'content':data['content']})
   if path=='git/trees':return put({'blob':data['tree'][0]['sha']})
   if path=='git/commits' and method=='POST':return put(data)
   if path=='git/refs' and method=='POST':
    if self.head:raise StateError('Branch exists')
    self.head=data['sha'];return {'ok':True}
   if path=='git/ref/heads/'+BRANCH:
    if not self.head:raise StateError('Missing history')
    return {'object':{'sha':self.head}}
   if path.startswith('git/commits/'):
    c=self.objects[path.split('/')[-1]];return {'tree':{'sha':c['tree']}}
   if path.startswith('contents/'):
    sha=path.split('ref=')[1];c=self.objects[sha];t=self.objects[c['tree']];blob=self.objects[t['blob']]
    return {'encoding':'base64','content':base64.b64encode(blob['content'].encode()).decode()}
   if path=='git/refs/heads/'+BRANCH:
    if data['force'] or self.fail_before_ref:raise StateError('Rejected')
    c=self.objects[data['sha']]
    if c['parents']!=[self.head]:raise StateError('Non fast-forward')
    self.head=data['sha']
    if self.fail_after_ref:raise StateError('Timeout after accepted ref')
    return {'ok':True}
   raise AssertionError(path)

class GitStateTests(unittest.TestCase):
 def setUp(self):
  self.key=Fernet.generate_key();self.api=FakeGit();self.repo='owner/repo'
  initialize(self.repo,self.key,self.api,{'control':{'kind':'control','paused':True}})
 def db(self):return GitHubState(self.repo,self.key,self.api)
 def test_roundtrip_is_encrypted_and_bound_to_repository(self):
  codec=Codec(self.key,self.repo);payload=codec.seal({'contact':'secret@example.com'})
  self.assertNotIn('secret@example.com',payload);self.assertEqual(codec.open(payload),{'contact':'secret@example.com'})
  with self.assertRaises(StateError):Codec(self.key,'other/repo').open(payload)
  with self.assertRaises(StateError):Codec(Fernet.generate_key(),self.repo).open(payload)
 def test_missing_state_never_initializes_implicitly(self):
  with self.assertRaises(StateError):GitHubState(self.repo,self.key,FakeGit())
 def test_initialization_cannot_reset_existing_history(self):
  head=self.api.head
  with self.assertRaises(StateError):initialize(self.repo,self.key,self.api,{})
  self.assertEqual(self.api.head,head)
 def test_read_and_noop_do_not_create_commits(self):
  db=self.db();head=self.api.head;db.get('control');db.transaction(lambda tx:tx.put('control',tx.get('control')))
  self.assertEqual(self.api.head,head)
 def test_successful_commit_survives_new_runner(self):
  self.db().transaction(lambda tx:tx.put('receipt',{'kind':'outbox','state':'sent'}))
  self.assertEqual(self.db().get('receipt')['state'],'sent')
 def test_sibling_writers_only_one_can_commit(self):
  first,second=self.db(),self.db();first.transaction(lambda tx:tx.put('claim',{'state':'sending'}))
  with self.assertRaises(StateError):second.transaction(lambda tx:tx.put('claim',{'state':'sending'}))
  self.assertTrue(second.broken)
  with self.assertRaises(StateError):second.get('claim')
 def test_timeout_after_ref_acceptance_never_allows_dispatch_or_reset(self):
  db=self.db();self.api.fail_after_ref=True
  with self.assertRaises(StateError):db.transaction(lambda tx:tx.put('claim',{'state':'sending'}))
  self.api.fail_after_ref=False
  self.assertEqual(self.db().get('claim')['state'],'sending')
  self.assertTrue(db.broken)
 def test_failed_write_preserves_previous_state_and_poisons_client(self):
  db=self.db();self.api.fail_before_ref=True
  with self.assertRaises(StateError):db.transaction(lambda tx:tx.put('claim',{'state':'sending'}))
  self.assertIsNone(self.db().get('claim'))
  with self.assertRaises(StateError):db.transaction(lambda tx:None)
 def test_transaction_callback_failure_has_no_remote_mutation(self):
  head=self.api.head
  def fail(tx):tx.put('x',{});raise ValueError('Validation')
  with self.assertRaises(ValueError):self.db().transaction(fail)
  self.assertEqual(head,self.api.head)
 def test_changed_state_after_claim_refuses_dispatch_check(self):
  first=self.db();second=self.db();second.transaction(lambda tx:tx.put('pause',True))
  with self.assertRaises(StateError):first.assert_current()
 def test_remote_claim_overlap_has_exactly_one_winner(self):
  fixture=fixtures.QueueTests();fixture.setUp()
  fixture.q.enqueue(fixture.item())
  api=FakeGit();initialize(self.repo,self.key,api,fixture.db.records)
  backends=[GitHubState(self.repo,self.key,api) for _ in range(8)];winners=[]
  def claim(db):
   try:Queue(db).claim('one',fixture.t,'approved',50,180,'Asia/Bangkok');winners.append(1)
   except StateError:pass
  threads=[threading.Thread(target=claim,args=(db,)) for db in backends]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(len(winners),1)
  final=GitHubState(self.repo,self.key,api)
  self.assertEqual(final.get('outbox_one')['state'],'sending');self.assertEqual(final.get('control')['days']['2026-10-19'],1)
