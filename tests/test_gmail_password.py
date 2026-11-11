import unittest
from unittest.mock import MagicMock, patch
from acquisition_agent.gmail_password import GmailPassword


class PasswordTransportTests(unittest.TestCase):
    def setUp(self):
        self.gmail = GmailPassword('shine@example.com', 'fake password')

    def test_missing_credentials_fail(self):
        with self.assertRaises(ValueError):
            GmailPassword('', '')

    def test_query_control_characters_rejected(self):
        with self.assertRaises(ValueError):
            self.gmail.quoted('x\r\nSEARCH ALL')

    def test_stable_ids_match_api_and_fetch_does_not_mark_read(self):
        client = MagicMock()
        raw = b'From: client@example.com\r\nTo: shine@example.com\r\nMessage-ID: <sample@example.com>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHello'
        meta = b'1 (X-GM-MSGID 255 X-GM-THRID 256 INTERNALDATE "11-Nov-2026 12:00:00 +0000"'
        client.uid.return_value = ('OK', [(meta, raw), b')'])
        message = self.gmail.fetch(client, b'42')
        self.assertEqual(message['id'], 'ff')
        self.assertEqual(message['threadId'], '100')
        self.assertIn('BODY.PEEK[]', client.uid.call_args.args[2])

    def test_missing_metadata_fails_closed(self):
        client = MagicMock()
        client.uid.return_value = ('OK', [(b'1 (', b'hello')])
        with self.assertRaises(ValueError):
            self.gmail.fetch(client, b'42')

    def test_duplicate_receipt_rejected(self):
        with patch.object(self.gmail, 'search', return_value=[{}, {}]):
            with self.assertRaises(ValueError):
                self.gmail.find_sent('<sample@example.com>')

    def test_no_receipt_after_smtp_acceptance_never_retries(self):
        with patch('acquisition_agent.gmail_password.smtplib.SMTP_SSL') as smtp, patch.object(self.gmail, 'find_sent', return_value=None):
            client = smtp.return_value.__enter__.return_value
            client.send_message.return_value = {}
            with self.assertRaisesRegex(ValueError, 'never resend'):
                self.gmail.send('shine@example.com', 'test@example.com', 'Test', 'Body', '<test@example.com>')
            self.assertEqual(client.send_message.call_count, 1)

    def test_positive_receipt_returns_stable_ids(self):
        with patch('acquisition_agent.gmail_password.smtplib.SMTP_SSL') as smtp, patch.object(self.gmail, 'find_sent', return_value={'id':'ff','threadId':'100'}):
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            result = self.gmail.send('shine@example.com', 'test@example.com', 'Test', 'Body', '<test@example.com>')
            self.assertEqual(result, {'id':'ff','threadId':'100'})

    def test_identity_only_authenticates(self):
        with patch.object(self.gmail, 'mailbox') as mailbox, patch('acquisition_agent.gmail_password.smtplib.SMTP_SSL') as smtp:
            self.assertEqual(self.gmail.identity(), 'shine@example.com')
            smtp.return_value.__enter__.return_value.send_message.assert_not_called()

    def test_transport_requires_explicit_selection(self):
        from hosted_sender.cli import gmail
        with patch.dict('os.environ', {'SHINE_MAIL_TRANSPORT':'app-password','EMAIL_USER':'shine@example.com','EMAIL_PASS':'fake'}):
            self.assertIsInstance(gmail('/unused'), GmailPassword)
