"""Compatibility, real adapter transport and approval workflow; no external email."""
import copy
import json
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
import test_notion_review
from acquisition_agent import notion_compat as c, delivery as d
from acquisition_agent.providers import Notion, rich, lead_properties
from acquisition_agent.connect_outreach import connect
from acquisition_agent.core import read_json, write_json

ROOT=Path(__file__).resolve().parent.parent


def typed(props):
    return {k:dict(v,type=next(k for k in v if k != 'type')) for k,v in props.items()}


class Transport:
    def __init__(self,lead):
        self.pages={'page':{'object':'page','id':'page','parent':{'data_source_id':c.SOURCE},'properties':typed(c.encode_props(lead_properties(dict(lead,score=70))))}}
        self.writes=[];self.fail=False
    def __call__(self,url,method,data,headers):
        if self.fail:raise ValueError('Notion unavailable')
        path=url.split('/v1/',1)[1]
        if path.startswith('data_sources/'):
            if path.endswith('/query'):
                pages=list(self.pages.values())
                f=(data or {}).get('filter')
                if f and f.get('property')=='Deduplication Key':
                    value=f['rich_text']['equals']
                    pages=[p for p in pages if ''.join(x['text']['content'] for x in p['properties'].get('Deduplication Key',{}).get('rich_text',[]))==value]
                return copy.deepcopy({'results':pages,'has_more':False})
            props={k:{'type':v} for k,v in c.REQUIRED.items()}
            props.update({k:{'type':'rich_text'} for k in ('Deduplication Key','Review Summary')})
            props.update({'Research Check':{'type':'select'},'Scheduled Time':{'type':'date'}})
            return {'object':'data_source','id':c.SOURCE,'properties':props}
        if path=='pages':
            key='created-'+str(len(self.pages));self.writes.append(copy.deepcopy(data))
            p={'object':'page','id':key,'parent':data['parent'],'properties':typed(data['properties'])};self.pages[key]=p
            return copy.deepcopy(p)
        key=path.split('/')[1]
        if method=='PATCH':
            self.writes.append(copy.deepcopy(data));self.pages[key]['properties'].update(typed(data['properties']))
        return copy.deepcopy(self.pages[key])


class BoundaryTests(unittest.TestCase):
    def test_roundtrip_uses_original_fields_and_select_types(self):
        p={'Name':{'title':rich('Cocoa')},'STATUS':{'status':{'name':'Approve'}},'COUNTRY':{'rich_text':rich('United Arab Emirates')},'Company Time Zone':{'select':{'name':'Asia/Dubai'}},'email SUBJECT':{'rich_text':rich('Subject')},'email body':{'rich_text':rich('Body')},'sent time':{'date':{'start':'2026-10-20'}},'Type':{'select':{'name':'Start-up'}}}
        before=copy.deepcopy(p);encoded=c.encode_props(p)
        self.assertEqual(p,before);self.assertEqual(encoded['STATUS'],{'select':{'name':'Approve'}})
        self.assertEqual(encoded['COUNTRY']['select']['name'],'UAE');self.assertEqual(encoded['Type']['select']['name'],'Startup')
        self.assertNotIn('email body',encoded);self.assertIn('BODY',encoded)
        decoded=c.decode_props(typed(encoded));self.assertEqual(decoded['STATUS']['status']['name'],'Approve')
        self.assertEqual(decoded['email body']['rich_text'],rich('Body'))
    def test_empty_country_and_status_are_safe(self):
        self.assertIsNone(c.encode_props({'COUNTRY':{'rich_text':[]}})['COUNTRY']['select'])
        self.assertIsNone(c.decode_props({'STATUS':{'select':None}})['STATUS']['status'])
    def test_filters_map_nested_status_without_changing_input(self):
        f={'and':[{'property':'STATUS','status':{'equals':'Approve'}},{'property':'Name','title':{'equals':'A'}}]};before=copy.deepcopy(f)
        out=c.encode_filter(f);self.assertEqual(f,before);self.assertEqual(out['and'][0]['select'],{'equals':'Approve'});self.assertEqual(out['and'][1]['property'],'NAME')
    def test_contact_history_matches_schemeless_www_and_exact_casefolded_email(self):
        p={'properties':{'WEBSITE':{'url':'www.brand.example/path'},'EMAIL':{'email':'HELLO@brand.example'}}}
        self.assertTrue(c.contact_match(p,{'website':'https://brand.example/'}))
        self.assertTrue(c.contact_match(p,{'email':'hello@BRAND.example'}))
        self.assertFalse(c.contact_match(p,{'website':'https://otherbrand.example','email':'other@brand.example'}))


class OriginalWorkflowTests(test_notion_review.NotionReviewTests):
    # Inherit every v16 approval/revocation/edit/reply/uncertain-send test,
    # but run through the actual Notion adapter with select-typed original fields.
    def setUp(self):
        super().setUp()
        self.transport=Transport(self.lead)
        self.addCleanup(patch.stopall)
        patch('acquisition_agent.providers.api_json',self.transport).start()
        patch('acquisition_agent.providers.time.sleep').start()
        patch.dict('os.environ',{'NOTION_TOKEN':'offline-test'}).start()
        n=Notion();n.connection={'source_id':c.SOURCE}
        n.props=self.transport.pages['page']['properties'];n.writes=self.transport.writes
        # Parent fixture references canonical fields directly; supply canonical
        # facade for inherited tests, while every transport request stays native.
        class Props:
            def __getitem__(_,key):
                raw=n._transport.pages['page']['properties'];return c.decode_props(raw)[key]
            def __setitem__(_,key,value):n._transport.pages['page']['properties'].update(typed(c.encode_props({key:value})))
        n._transport=self.transport;n.props=Props()
        def status(value):n.props['STATUS']={'status':{'name':value}}
        n.status=status
        # Replicate the parent fixture's failure switch at the transport boundary.
        original=n.request
        def request(path,method='POST',data=None):
            if getattr(n,'fail_patch',False) and method=='PATCH':raise ValueError('Notion offline')
            return original(path,method,data)
        n.request=request;self.n=n
    def test_preparation_writes_evidence_and_summary_without_human_approval(self):
        self.prepare();raw=self.transport.pages['page']['properties']
        self.assertEqual(raw['Research Check']['select']['name'],'Ready for review');self.assertEqual(raw['STATUS']['select']['name'],'Draft')
        self.assertEqual(raw['Time Zone']['select']['name'],'Asia/Dubai');self.assertNotIn('Company Time Zone',raw)
        self.assertNotIn('email body',raw);self.assertNotIn('email SUBJECT',raw)
        self.assertFalse(any(x.get('properties',{}).get('STATUS',{}).get('select',{}).get('name')=='Approve' for x in self.transport.writes))
        self.gmail.send.assert_not_called()
    def test_preparation_preserves_notion_message_edits(self):
        body=self.lead['draft']['body']+' Owner-edited wording.';self.n.props['email body']={'rich_text':rich(body)}
        self.prepare();self.assertEqual(self.n.props['email body']['rich_text'],rich(body))
    def test_historical_contact_blocks_before_queue_and_after_approval(self):
        self.prepare();self.n.status('Approve')
        self.transport.pages['legacy']={'object':'page','id':'legacy','properties':{'NAME':{'title':rich('Historical Cocoa')},'STATUS':{'select':{'name':'Sent'}},'EMAIL':{'email':'office@paper.example'}}}
        self.assertIn('Existing Outreach record',self.queue()[0]['held']);self.assertEqual(d.rows(self.store),[])
        self.gmail.send.assert_not_called()
    def test_legacy_ready_is_not_new_approval(self):
        self.prepare();self.n.status('Ready');self.n.props['Approved']={'checkbox':True}
        self.assertIn('held',self.queue()[0]);self.assertEqual(d.rows(self.store),[])
    def test_missing_history_access_fails_closed_before_send(self):
        self.approve();self.transport.fail=True
        self.assertNotEqual(self.tick(self.due()+timedelta(seconds=1))['state'],'sent');self.gmail.send.assert_not_called()
    def test_sync_refuses_to_overwrite_an_unowned_legacy_record(self):
        self.transport.pages['page']['properties'].pop('Deduplication Key',None)
        lead=copy.deepcopy(self.lead);lead['draft_dirty']=True
        before=copy.deepcopy(self.transport.pages['page'])
        with self.assertRaisesRegex(ValueError,'not owned'):self.n.save_lead(c.SOURCE,lead)
        self.assertEqual(before,self.transport.pages['page'])
    def test_create_retry_finds_existing_key_without_duplicate(self):
        lead=copy.deepcopy(self.lead);lead.pop('notion_page_id');lead['draft_dirty']=False
        self.n.save_lead(c.SOURCE,lead);self.assertEqual(lead['notion_page_id'],'page');self.assertEqual(len(self.transport.pages),1)
    def test_patch_to_old_agent_page_keeps_its_original_schema(self):
        self.transport.pages['old']={'object':'page','id':'old','properties':{'Name':{'title':rich('Old')},'STATUS':{'status':{'name':'Draft'}}}}
        self.n.request('pages/old','PATCH',{'properties':{'email body':{'rich_text':rich('Preserved')}}})
        self.assertIn('email body',self.transport.pages['old']['properties']);self.assertNotIn('BODY',self.transport.pages['old']['properties'])


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);shutil.copytree(ROOT/'config',self.root/'config');(self.root/'state').mkdir()
        (self.root/'state/agent.sqlite3').write_bytes(b'durable-history')
        self.fake=unittest.mock.Mock()
        types={'Name':'title','email SUBJECT':'rich_text','email body':'rich_text','STATUS':'status','COUNTRY':'rich_text','Company Time Zone':'select','EMAIL':'email','WEBSITE':'url','Deduplication Key':'rich_text','Research Check':'select','Scheduled Time':'date','Review Summary':'rich_text'}
        self.fake.request.return_value={'properties':{k:{'type':v} for k,v in types.items()}}
        self.fake.query.return_value=[{'id':'legacy'}]
    def test_verified_connection_preserves_history_and_policy(self):
        from acquisition_agent.updater import manifest
        config=read_json(self.root/'config/preferences.json');config['notion_leads_source_id']='59935700-60fe-4dea-82c8-eae6806a81b5';write_json(self.root/'config/preferences.json',config)
        write_json(self.root/'state/test-evidence.json',{'reply_verified':True});write_json(self.root/'state/sending-approval.json',{'sha256':d.fingerprint(manifest(self.root))})
        sending=(self.root/'config/sending.json').read_bytes()
        result=connect(self.root,self.fake)
        self.assertEqual(read_json(self.root/'config/preferences.json')['notion_leads_source_id'],c.SOURCE)
        self.assertEqual((self.root/'state/agent.sqlite3').read_bytes(),b'durable-history');self.assertEqual(sending,(self.root/'config/sending.json').read_bytes())
        self.assertEqual(read_json(self.root/'state/sending-approval.json')['sha256'],d.fingerprint(manifest(self.root)));self.assertTrue(result['policy_approval_preserved'])
        self.assertFalse(self.fake.request.call_args_list[0].args[1]=='PATCH')
    def test_missing_access_leaves_destination_and_approval_unchanged(self):
        before=(self.root/'config/preferences.json').read_bytes();self.fake.request.side_effect=ValueError('404')
        with self.assertRaisesRegex(ValueError,'unchanged'):connect(self.root,self.fake)
        self.assertEqual(before,(self.root/'config/preferences.json').read_bytes());self.assertFalse((self.root/'config/notion_connection.json').exists())
