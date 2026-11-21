import unittest
from email.message import EmailMessage
from acquisition_agent.portfolio_message import linked_portfolio,set_message_content,LINK
from acquisition_agent.commercial import OUTREACH_PORTFOLIO

class PortfolioMessageTests(unittest.TestCase):
 def test_old_raw_and_markdown_links_become_named_website_link(self):
  url='https://www.figma.com/design/Fy8kepSEJnGAZlt6Wi001T/Email-Design?node-id=0-1'
  for text in (url,'[Portfolio]('+url+')',OUTREACH_PORTFOLIO,LINK):
   self.assertEqual(linked_portfolio(text),LINK)
   self.assertEqual(linked_portfolio(linked_portfolio(text)),LINK)
 def test_mime_contains_clickable_label_and_plain_fallback(self):
  m=EmailMessage();set_message_content(m,'Hello <script>alert(1)</script>\n'+LINK)
  self.assertEqual(m.get_content_type(),'multipart/alternative')
  plain=m.get_body(preferencelist=('plain',)).get_content();html=m.get_body(preferencelist=('html',)).get_content()
  self.assertIn('View my portfolio: '+OUTREACH_PORTFOLIO,plain)
  self.assertIn('<a href="'+OUTREACH_PORTFOLIO+'">View my portfolio</a>',html)
  self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
 def test_unrelated_message_and_urls_stay_plain(self):
  body='Other source https://www.figma.com/design/Unrelated/Job';self.assertEqual(linked_portfolio(body),body)
  m=EmailMessage();set_message_content(m,body);self.assertFalse(m.is_multipart())
