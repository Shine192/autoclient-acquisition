import unittest
from acquisition_agent.verification import test_reply_found


class ReplyVerificationTests(unittest.TestCase):
    def message(self, id, **headers):
        return {'id':id, 'payload':{'headers':[{'name':k.replace('_','-'),'value':v} for k,v in headers.items()]}}

    def test_provider_rewritten_id_and_nested_reply(self):
        original = self.message('sent', From='me@example.com', To='me@example.com', Message_ID='<rewritten@gmail.com>')
        direct = self.message('reply', From='Me <me@example.com>', To='me@example.com', In_Reply_To='<rewritten@gmail.com>')
        nested = self.message('nested', From='me@example.com', To='me@example.com', In_Reply_To='<other@gmail.com>', References='<rewritten@gmail.com> <other@gmail.com>')
        for reply in (direct, nested):
            self.assertTrue(test_reply_found([original,reply], {'gmail_id':'sent','message_id':'<old@example.com>'}, 'me@example.com'))

    def test_reject_unlinked_missing_original_wrong_sender_and_draft(self):
        original = self.message('sent', From='me@example.com', To='me@example.com', Message_ID='<rewritten@gmail.com>')
        reply = self.message('reply', From='me@example.com', To='me@example.com', In_Reply_To='<rewritten@gmail.com>')
        self.assertFalse(test_reply_found([reply], {'gmail_id':'sent'}, 'me@example.com'))
        self.assertFalse(test_reply_found([original], {'gmail_id':'sent'}, 'me@example.com'))
        wrong = self.message('wrong', From='other@example.com', To='me@example.com', In_Reply_To='<rewritten@gmail.com>')
        self.assertFalse(test_reply_found([original,wrong], {'gmail_id':'sent'}, 'me@example.com'))
        reply['labelIds']=['DRAFT']
        self.assertFalse(test_reply_found([original,reply], {'gmail_id':'sent'}, 'me@example.com'))
