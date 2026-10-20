"""Local desktop OAuth and Gmail REST. No automatic retry of message sends."""
import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from email.message import EmailMessage
from email.policy import SMTP
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import parse, request, error
from .network import api_json, NoRedirect

SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + secrets.token_hex(4))
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle)
    os.replace(str(temp), str(path))
    os.chmod(str(path), 0o600)


def token_request(data):
    req = request.Request('https://oauth2.googleapis.com/token', data=parse.urlencode(data).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            return json.loads(response.read(100000))
    except (error.URLError, ValueError):
        raise ValueError('Google token request failed; reauthorize if necessary. No message was sent.') from None


def authorize(client_file, token_file, sender, manual_browser=False):
    client = json.loads(Path(client_file).read_text()).get('installed')
    if not client or not client.get('client_id') or not client.get('client_secret'):
        raise ValueError('Download a Desktop app OAuth client JSON from Google Cloud')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    result = {}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            parts = parse.urlsplit(self.path)
            values = parse.parse_qs(parts.query)
            valid = parts.path == '/callback' and secrets.compare_digest(values.get('state', [''])[0], state)
            if valid:
                result.update({key: values.get(key, [''])[0] for key in ('code', 'error')})
            self.send_response(200 if valid else 400)
            self.end_headers()
            self.wfile.write(b'Authorization received. Return to Terminal.' if valid else b'Invalid callback.')
    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        redirect = 'http://127.0.0.1:' + str(server.server_port) + '/callback'
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + parse.urlencode({'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code', 'scope': ' '.join(SCOPES), 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent', 'login_hint': sender})
        url_file = Path(token_file).parent / 'authorization-url.json'
        private_json(url_file, {'url': url})
        if manual_browser:
            print('Authorization is ready. Open the URL in ' + str(url_file) + ' in your browser within 5 minutes.', flush=True)
        else:
            print('Opening Google authorization in your browser. Complete it within 5 minutes. If it does not open, use the URL in ' + str(url_file), flush=True)
            webbrowser.open(url)
        server.timeout = 1
        deadline = time.time() + 300
        while not result and time.time() < deadline:
            server.handle_request()
    if not result.get('code'):
        raise ValueError('Google authorization cancelled or timed out')
    tokens = token_request({'client_id': client['client_id'], 'client_secret': client['client_secret'], 'code': result['code'], 'code_verifier': verifier, 'redirect_uri': redirect, 'grant_type': 'authorization_code'})
    if not tokens.get('refresh_token'):
        raise ValueError('Google did not return offline access; reauthorize with consent')
    tokens.update(client_id=client['client_id'], client_secret=client['client_secret'], expires_at=time.time() + tokens.get('expires_in', 3600))
    # Verify account before persisting credentials for the worker.
    profile = api_json('https://gmail.googleapis.com/gmail/v1/users/me/profile', 'GET', headers={'Authorization': 'Bearer ' + tokens['access_token']})
    if profile['emailAddress'].lower() != sender.lower():
        raise ValueError('Authorized account does not match configured sender')
    private_json(token_file, tokens)
    return profile['emailAddress']


class Gmail:
    def __init__(self, token_file):
        self.token_file = Path(token_file)

    def access(self):
        if not self.token_file.exists():
            raise ValueError('Run gmail-auth first; local Gmail credentials are missing')
        tokens = json.loads(self.token_file.read_text())
        if tokens.get('expires_at', 0) < time.time() + 90:
            fresh = token_request({'client_id': tokens['client_id'], 'client_secret': tokens['client_secret'], 'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token'})
            tokens.update(fresh)
            tokens['expires_at'] = time.time() + fresh.get('expires_in', 3600)
            private_json(self.token_file, tokens)
        return tokens['access_token']

    def call(self, path, method='GET', data=None):
        return api_json('https://gmail.googleapis.com/gmail/v1/users/me/' + path, method, data, {'Authorization': 'Bearer ' + self.access()})

    def identity(self):
        return self.call('profile')['emailAddress'].lower()

    def prior_contact(self, recipient):
        result = self.call('messages?' + parse.urlencode({'q': 'in:sent to:' + recipient, 'maxResults': 1}))
        return bool(result.get('messages'))

    def prior_company_contact(self,domain):
        # Conservative history check for an older sender that did not retain a
        # durable company ledger. A possible match holds for manual review.
        if not __import__('re').fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',domain):raise ValueError('Invalid company domain')
        result=self.call('messages?'+parse.urlencode({'q':'in:sent to:'+domain,'maxResults':1}))
        return bool(result.get('messages'))

    def find_sent(self, message_id):
        result = self.call('messages?' + parse.urlencode({'q': 'in:sent rfc822msgid:' + message_id, 'maxResults': 10}))
        matches = result.get('messages', [])
        if len(matches) > 1:
            raise ValueError('Multiple matching sent messages; manual investigation required')
        return matches[0] if matches else None

    def send(self, sender, recipient, subject, body, message_id, thread_id='', reply_to=''):
        message = EmailMessage(policy=SMTP)
        message['From'], message['To'], message['Subject'] = sender, recipient, subject
        message['Message-ID'] = message_id
        if reply_to:
            message['In-Reply-To'] = reply_to
            message['References'] = reply_to
        message.set_content(body)
        data = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        if thread_id:
            data['threadId'] = thread_id
        return self.call('messages/send', 'POST', data)

    def message(self, message_id):
        return self.call('messages/' + parse.quote(message_id, safe='') + '?format=full')

    def thread(self, thread_id):
        return self.call('threads/' + parse.quote(thread_id, safe='') + '?format=full').get('messages', [])

    def related(self, recipient, since):
        # Catch new-thread replies and DSNs, not only replies Gmail threaded.
        date = int(since)
        query = 'after:' + str(date) + ' {from:' + recipient + ' from:mailer-daemon from:postmaster}'
        cursor, output = '', []
        for _ in range(10):
            params = {'q': query, 'maxResults': 100, 'includeSpamTrash': 'true'}
            if cursor:
                params['pageToken'] = cursor
            result = self.call('messages?' + parse.urlencode(params))
            for item in result.get('messages', []):
                output.append(self.call('messages/' + item['id'] + '?format=full'))
            cursor = result.get('nextPageToken')
            if not cursor:
                return output
        raise ValueError('Reply scan exceeds 1000 messages; review inbox before sending')
