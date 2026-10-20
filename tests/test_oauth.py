"""Desktop OAuth contract tests: simulated loopback/Google responses, no network."""
import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import MagicMock, Mock, patch
from acquisition_agent.gmail import authorize

class OAuthTests(unittest.TestCase):
    def run_flow(self, identity='owner@example.com', wrong_state_first=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        client = root / 'client.json'
        client.write_text(json.dumps({'installed':{'client_id':'desktop-id','client_secret':'fake-secret','project_id':'fake-project'}}))
        token = root / 'token.json'
        server = MagicMock()
        server.server_port = 12345
        server.__enter__.return_value = server
        callbacks = []
        responses = []
        def factory(address, handler):
            def receive():
                url = json.loads((root/'authorization-url.json').read_text())['url']
                values = parse_qs(urlsplit(url).query)
                state = 'wrong-state' if wrong_state_first and not callbacks else values['state'][0]
                callbacks.append(state)
                instance = object.__new__(handler)
                instance.path = '/callback?' + urlencode({'state':state,'code':'fake-code'})
                instance.send_response = lambda code: responses.append(code)
                instance.end_headers = Mock()
                instance.wfile = io.BytesIO()
                instance.do_GET()
            server.handle_request.side_effect = receive
            return server
        token_result = {'access_token':'fake-access','refresh_token':'fake-refresh','expires_in':3600}
        with patch('acquisition_agent.gmail.HTTPServer',side_effect=factory), patch('acquisition_agent.gmail.webbrowser.open') as browser, patch('acquisition_agent.gmail.token_request',return_value=token_result) as exchange, patch('acquisition_agent.gmail.api_json',return_value={'emailAddress':identity}):
            if identity != 'owner@example.com':
                with self.assertRaisesRegex(ValueError,'does not match'):
                    authorize(client,token,'owner@example.com',manual_browser=True)
                self.assertFalse(token.exists())
                return
            result = authorize(client,token,'owner@example.com',manual_browser=True)
            self.assertEqual(result,'owner@example.com')
            browser.assert_not_called()
            self.assertEqual(token.stat().st_mode & 0o777,0o600)
            values = parse_qs(urlsplit(json.loads((root/'authorization-url.json').read_text())['url']).query)
            verifier = exchange.call_args[0][0]['code_verifier']
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            self.assertEqual(values['code_challenge'],[challenge])
            self.assertEqual(values['redirect_uri'],['http://127.0.0.1:12345/callback'])
            self.assertNotIn('client_secret', values)
            self.assertEqual(responses,[400,200] if wrong_state_first else [200])

    def test_manual_browser_keeps_pkce_and_private_tokens(self):
        self.run_flow()

    def test_invalid_callback_state_rejected_before_valid_callback(self):
        self.run_flow(wrong_state_first=True)

    def test_wrong_google_account_never_persists_token(self):
        self.run_flow(identity='another@example.com')
