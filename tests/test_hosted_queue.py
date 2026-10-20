import copy
import threading
import unittest
from datetime import datetime, timezone
from hosted_sender.queue import Queue

class Memory:
    def __init__(self): self.records={};self.lock=threading.RLock()
    def transaction(self,fn):
        with self.lock:
            proposed=copy.deepcopy(self.records)
            class Tx:
                def get(self,k):return copy.deepcopy(proposed.get(k))
                def put(self,k,v):proposed[k]=copy.deepcopy(v)
            result=fn(Tx());self.records=proposed;return result
    def get(self,k):return self.transaction(lambda tx:tx.get(k))
    def list(self,kind,limit=200):return [copy.deepcopy(v) for v in self.records.values() if v.get('kind')==kind]

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.db=Memory();self.q=Queue(self.db);self.q.init()
        self.t=datetime(2026,10,19,6,tzinfo=timezone.utc).timestamp()
        self.q.campaign('a',{'dates':['2026-10-19'],'start_date':'2026-10-19','end_date':'2026-10-19','maximum_sends':20,'settings_hash':'approved'})
        self.db.records['control'].update(paused=False,migration_complete=True,test_verified=True,approved_hash='approved')
    def item(self,k='one',recipient='hello@example.com',company='example.com'):
        return {'id':k,'recipient':recipient,'company':company,'campaign':'a','company_timezone':'Asia/Dubai','due_at':self.t,'lead_id':k}
    def claim(self,k='one',t=None,limit=10):return self.q.claim(k,t or self.t,'approved',limit,300,'Asia/Bangkok')
    def test_defaults(self):
        q=Queue(Memory());q.init();self.assertTrue(q.control()['paused']);self.assertFalse(q.control()['migration_complete'])
    def test_idempotent(self):
        self.q.enqueue(self.item());self.q.enqueue(self.item());self.assertEqual(len(self.db.list('outbox')),1)
    def test_recipient_duplicate(self):
        self.q.enqueue(self.item())
        with self.assertRaises(ValueError):self.q.enqueue(self.item('two',company='other.com'))
    def test_company_duplicate(self):
        self.q.enqueue(self.item())
        with self.assertRaises(ValueError):self.q.enqueue(self.item('two',recipient='other@example.com'))
    def test_concurrent_one_winner(self):
        self.q.enqueue(self.item());winners=[]
        def run():
            try:self.claim();winners.append(1)
            except ValueError:pass
        threads=[threading.Thread(target=run) for _ in range(16)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(winners),1);self.assertEqual(self.q.control()['days']['2026-10-19'],1)
    def test_crash_never_reclaimed(self):
        self.q.enqueue(self.item());self.claim()
        with self.assertRaises(ValueError):self.claim(t=self.t+86400*5)
    def test_uncertain_blocks_all(self):
        self.q.enqueue(self.item());self.q.enqueue(self.item('two','hi@other.com','other.com'))
        self.claim();self.q.outcome('one',error='timeout')
        with self.assertRaises(ValueError):self.claim('two',self.t+600)
        self.assertEqual(self.db.get('outbox_one')['state'],'uncertain')
    def test_interval(self):
        self.q.enqueue(self.item());self.q.enqueue(self.item('two','hi@other.com','other.com'))
        self.claim();self.q.outcome('one',{'id':'g1','threadId':'t1'})
        with self.assertRaises(ValueError):self.claim('two',self.t+1)
        self.claim('two',self.t+300)
    def test_daily_cap(self):
        self.q.enqueue(self.item());self.q.enqueue(self.item('two','hi@other.com','other.com'))
        self.claim(limit=1);self.q.outcome('one',{'id':'g1','threadId':'t1'})
        with self.assertRaises(ValueError):self.claim('two',self.t+300,limit=1)
    def test_parent_domain_suppression(self):
        self.q.enqueue(self.item(recipient='hi@sub.example.com',company='sub.example.com'));self.q.suppress(['example.com'],'Opt-out')
        with self.assertRaises(ValueError):self.claim()
    def test_changed_policy(self):
        self.q.enqueue(self.item());self.db.records['control']['approved_hash']='old'
        with self.assertRaises(ValueError):self.claim()
    def test_selected_dates(self):
        self.q.enqueue(self.item())
        with self.assertRaises(ValueError):self.claim(t=self.t+86400)
    def test_pause(self):
        self.q.enqueue(self.item());self.q.pause()
        with self.assertRaises(ValueError):self.claim()
    def test_incomplete_receipt(self):
        self.q.enqueue(self.item());self.claim();self.q.outcome('one',{'id':'g'})
        self.assertEqual(self.q.control()['active_attempt'],'one')
    def test_no_reset(self):
        with self.assertRaises(ValueError):self.q.init()
    def test_no_followup(self):
        with self.assertRaises(ValueError):self.q.enqueue(dict(self.item(),stage=1))
    def test_reapproved_blocked_contact_reserves_changed_recipient_atomically(self):
        self.q.enqueue(self.item());self.q.hold('one','Draft changed')
        self.db.records['outbox_one']['approval_reset_done']=True
        self.q.enqueue(self.item(recipient='new@example.com'))
        with self.assertRaises(ValueError):self.q.enqueue(self.item('two',recipient='new@example.com',company='other.com'))
    def test_no_weekend(self):
        with self.assertRaises(ValueError):self.q.campaign('bad',{'dates':['2026-10-24'],'start_date':'2026-10-24','end_date':'2026-10-24','maximum_sends':1})
    def test_receipt_requires_owner(self):
        self.q.enqueue(self.item())
        with self.assertRaises(ValueError):self.q.outcome('one',{'id':'g','threadId':'t'})

if __name__=='__main__':unittest.main()
