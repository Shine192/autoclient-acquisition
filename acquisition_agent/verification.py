"""Verify a self-test using the provider's actual sent-message headers."""
import re
from email.utils import getaddresses


def test_reply_found(messages, item, sender):
    # Gmail can replace the submitted Message-ID. Anchor to the immutable API
    # receipt, then use that exact message's provider-assigned RFC Message-ID.
    original = next((m for m in messages if m.get('id') == item['gmail_id']), None)
    if original is None:
        return False
    def headers(message):
        return {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}
    original_headers = headers(original)
    actual_id = original_headers.get('message-id', '').strip()
    if not re.fullmatch(r'<[^<>\s]+@[^<>\s]+>', actual_id):
        return False
    def addresses(value):
        return {address.lower() for _, address in getaddresses([value])}
    sender = sender.lower()
    if sender not in addresses(original_headers.get('from', '')) or sender not in addresses(original_headers.get('to', '')):
        return False
    for message in messages:
        if message.get('id') == item['gmail_id'] or 'DRAFT' in message.get('labelIds', []):
            continue
        h = headers(message)
        linked_ids = re.findall(r'<[^<>\s]+@[^<>\s]+>', h.get('in-reply-to', '') + ' ' + h.get('references', ''))
        if actual_id in linked_ids and sender in addresses(h.get('from', '')) and sender in addresses(h.get('to', '')):
            return True
    return False
