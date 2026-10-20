import tempfile
import unittest
from pathlib import Path
from acquisition_agent.update_launcher import candidates,select

class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent=Path(self.temp.name);self.source=self.parent/'shine-update';self.source.mkdir()

    def app(self,name,state=True):
        path=self.parent/name
        for filename in ('config/profile.json','config/sending.json','acquisition_agent/__main__.py')+ (('state/agent.sqlite3',) if state else ()):
            target=path/filename;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('fixture')
        return path.resolve()

    def test_missing_version_folder_finds_original_saved_installation(self):
        original=self.app('shine-acquisition-agent')
        self.app('shine-acquisition-agent-v0.13.0',False)
        self.assertEqual(select(self.source,ask=lambda _:self.fail('Should auto-detect sole installation'),show=lambda _:None),original)

    def test_multiple_installations_require_explicit_selection(self):
        first=self.app('shine-acquisition-agent');second=self.app('shine-acquisition-agent-v0.12.0')
        self.assertEqual(select(self.source,ask=lambda _:'2',show=lambda _:None),second)
        self.assertEqual(select(self.source,ask=lambda _:'1',show=lambda _:None),first)
        with self.assertRaises(ValueError):select(self.source,ask=lambda _:'3',show=lambda _:None)

    def test_current_source_and_template_are_never_selected(self):
        for filename in ('config/profile.json','config/sending.json','acquisition_agent/__main__.py','state/agent.sqlite3'):
            p=self.source/filename;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
        self.app('template',False)
        self.assertEqual(candidates(self.source),[])
        with self.assertRaises(ValueError):select(self.source,ask=lambda _:str(self.source),show=lambda _:None)

    def test_dragged_quoted_folder_path_is_parsed_without_shell_execution(self):
        outside=self.parent/'outside';outside.mkdir();source=outside/'update';source.mkdir()
        app=self.app('Shine saved app')
        self.assertEqual(select(source,ask=lambda _:"'"+str(app)+"'",show=lambda _:None),app)

    def test_no_match_rejects_arbitrary_folder(self):
        with self.assertRaises(ValueError):select(self.source,ask=lambda _:str(self.parent),show=lambda _:None)
