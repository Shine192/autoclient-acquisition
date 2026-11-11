"""Gmail App Password transport. SMTP never retries; receipts require IMAP evidence.

Gmail's stable X-GM-MSGID/X-GM-THRID values are represented as hex, matching
the Gmail API IDs already stored in the ledger. UID values are never persisted.
"""
import base64
import imaplib
import re
import smtplib
import ssl
from contextlib import contextmanager
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser


class GmailPassword:
    def __init__(self, sender, password):
        self.sender = sender.strip().lower()
        self.password = password.replace(' ', '')
        if not self.sender or not self.password:
            raise ValueError('Gmail App Password credentials are missing')

    @contextmanager
    def mailbox(self, special=b'\\All'):
        client = imaplib.IMAP4_SSL('imap.gmail.com', 993,
                                    ssl_context=ssl.create_default_context(), timeout=30)
        try:
            client.login(self.sender, self.password)
            status, rows = client.list()
            if status != 'OK':
                raise ValueError('Cannot discover Gmail All Mail folder')
            folder = None
            for row in rows:
                if row and special in row.split(b')', 1)[0].replace(b'(', b' ').split():
                    match = re.search(rb'\) "[^"]*" (.+)$', row)
                    if match:
                        folder = match.group(1).decode('utf-8')
            if not folder:
                raise ValueError('Enable Gmail All Mail access in IMAP before sending')
            if client.select(folder, readonly=True)[0] != 'OK':
                raise ValueError('Cannot read Gmail All Mail folder')
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                pass

    @staticmethod
    def quoted(value):
        if any(c in value for c in '\r\n\x00'):
            raise ValueError('Invalid Gmail search')
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def search(self, query, maximum=1000):
        output = {}
        folders = (b'\\All', b'\\Junk', b'\\Trash') if 'in:anywhere' in query else (b'\\All',)
        for folder in folders:
            with self.mailbox(folder) as client:
                status, rows = client.uid('SEARCH', None, 'X-GM-RAW', self.quoted(query))
                if status != 'OK':
                    raise ValueError('Gmail search failed; sending stopped')
                uids = (rows[0] or b'').split()
                if len(uids) > maximum:
                    raise ValueError('Gmail search exceeds safe limit; review mailbox')
                for uid in uids:
                    item = self.fetch(client, uid)
                    output[item['id']] = item
                if len(output) > maximum:
                    raise ValueError('Gmail search exceeds safe limit; review mailbox')
        return list(output.values())

    @staticmethod
    def fetch(client, uid):
        status, rows = client.uid('FETCH', uid, '(X-GM-MSGID X-GM-THRID X-GM-LABELS INTERNALDATE BODY.PEEK[])')
        if status != 'OK':
            raise ValueError('Gmail message read failed')
        pair = next((r for r in rows if isinstance(r, tuple)), None)
        if not pair:
            raise ValueError('Gmail message metadata missing')
        meta, raw = pair
        mid = re.search(rb'X-GM-MSGID (\d+)', meta)
        tid = re.search(rb'X-GM-THRID (\d+)', meta)
        date = re.search(rb'INTERNALDATE "([^"]+)"', meta)
        if not mid or not tid or not date:
            raise ValueError('Gmail stable receipt metadata missing')
        received = datetime.strptime(date.group(1).decode('ascii'), '%d-%b-%Y %H:%M:%S %z')
        message = BytesParser(policy=policy.default).parsebytes(raw)
        parts = []
        for part in message.walk():
            if part.get_content_type() == 'text/plain':
                content = part.get_payload(decode=True) or b''
                parts.append(content.decode(part.get_content_charset() or 'utf-8', errors='replace'))
        body = '\n'.join(parts)
        label_match = re.search(rb'X-GM-LABELS \(([^)]*)\)', meta)
        raw_labels = label_match.group(1) if label_match else b''
        labels = [name for tag, name in ((b'\\Sent', 'SENT'), (b'\\Drafts', 'DRAFT')) if tag in raw_labels]
        # Search predicates determine Sent membership; don't infer it from From.
        return {'id': format(int(mid.group(1)), 'x'),
                'threadId': format(int(tid.group(1)), 'x'),
                'internalDate': str(int(received.timestamp() * 1000)), 'labelIds': labels,
                'snippet': '', 'payload': {'mimeType': 'text/plain',
                'headers': [{'name': k, 'value': str(v)} for k, v in message.items()],
                'body': {'data': base64.urlsafe_b64encode(body.encode()).decode()}}}

    def identity(self):
        # Test both protocols without transmitting a message.
        with self.mailbox():
            pass
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30,
                              context=ssl.create_default_context()) as client:
            client.login(self.sender, self.password)
        return self.sender

    def prior_contact(self, recipient):
        return bool(self.search('in:sent to:' + self.quoted(recipient)))

    def prior_company_contact(self, domain):
        if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', domain):
            raise ValueError('Invalid company domain')
        return bool(self.search('in:sent to:' + domain))

    def find_sent(self, message_id):
        matches = self.search('in:sent rfc822msgid:' + self.quoted(message_id))
        if len(matches) > 1:
            raise ValueError('Multiple sent receipts; manual investigation required')
        if matches:
            matches[0]['labelIds'] = ['SENT']
            return matches[0]
        return None

    def message(self, message_id):
        if not re.fullmatch(r'[0-9a-f]+', message_id):
            raise ValueError('Invalid Gmail message ID')
        with self.mailbox() as client:
            status, rows = client.uid('SEARCH', None, 'X-GM-MSGID', str(int(message_id, 16)))
            if status != 'OK' or len((rows[0] or b'').split()) != 1:
                raise ValueError('Saved Gmail receipt unavailable')
            result = self.fetch(client, rows[0].split()[0])
        headers = {h['name'].lower():h['value'] for h in result['payload']['headers']}
        sent = self.find_sent(headers.get('message-id', '')) if headers.get('message-id') else None
        if sent and sent['id'] == result['id']:
            result['labelIds'] = ['SENT']
        return result

    def thread(self, thread_id):
        if not re.fullmatch(r'[0-9a-f]+', thread_id):
            raise ValueError('Invalid Gmail thread ID')
        with self.mailbox() as client:
            status, rows = client.uid('SEARCH', None, 'X-GM-THRID', str(int(thread_id, 16)))
            if status != 'OK':
                raise ValueError('Gmail thread lookup failed')
            uids = (rows[0] or b'').split()
            if len(uids) > 1000:
                raise ValueError('Gmail thread exceeds safe limit')
            return [self.fetch(client, uid) for uid in uids]

    def related(self, recipient, since):
        return self.search('in:anywhere after:' + str(int(since)) +
                           ' {from:' + self.quoted(recipient) + ' from:mailer-daemon from:postmaster}')

    def send(self, sender, recipient, subject, body, message_id, thread_id='', reply_to=''):
        if sender.lower() != self.sender:
            raise ValueError('Wrong SMTP sender')
        message = EmailMessage(policy=policy.SMTP)
        message['From'], message['To'], message['Subject'] = sender, recipient, subject
        message['Message-ID'] = message_id
        if reply_to:
            message['In-Reply-To'] = reply_to
            message['References'] = reply_to
        message.set_content(body)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30,
                              context=ssl.create_default_context()) as client:
            client.login(self.sender, self.password)
            if client.send_message(message, from_addr=sender, to_addrs=[recipient]):
                raise ValueError('SMTP recipient refused; manual review required')
        receipt = self.find_sent(message_id)
        if not receipt:
            raise ValueError('SMTP accepted but Sent receipt not visible; reconcile, never resend')
        return {'id':receipt['id'], 'threadId':receipt['threadId']}
