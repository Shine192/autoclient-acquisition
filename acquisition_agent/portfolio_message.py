"""Restricted portfolio-link formatting; message text is never interpreted as HTML."""
import re
from html import escape
from .commercial import OUTREACH_PORTFOLIO

LABEL='View my portfolio'
LINK='['+LABEL+']('+OUTREACH_PORTFOLIO+')'
FIGMA=r'https://(?:www\.)?figma\.com/(?:design|file)/(?:Fy8kepSEJnGAZlt6Wi001T|ADkHTEIJLd52MjGcIT1sfX)/[^\s<>\)\]]*'

def linked_portfolio(body):
    body=re.sub(r'\[[^\]\n]*\]\(('+FIGMA+r')\)',LINK,body)
    body=re.sub(FIGMA,LINK,body)
    # Normalize a prior website label or bare website URL exactly once.
    token='\x00PORTFOLIO\x00'
    body=re.sub(r'\[[^\]\n]*\]\('+re.escape(OUTREACH_PORTFOLIO)+r'/?\)',token,body)
    body=re.sub(re.escape(OUTREACH_PORTFOLIO)+r'/?(?![\w/?#.-])',token,body)
    return body.replace(token,LINK)

def set_message_content(message,body):
    if OUTREACH_PORTFOLIO not in body:
        message.set_content(body);return
    formatted=linked_portfolio(body)
    plain=formatted.replace(LINK,LABEL+': '+OUTREACH_PORTFOLIO)
    message.set_content(plain)
    html=escape(formatted).replace(escape(LINK),'<a href="'+escape(OUTREACH_PORTFOLIO,quote=True)+'">'+LABEL+'</a>')
    message.add_alternative('<html><body><div style="white-space:pre-wrap;font-family:Arial,sans-serif">'+html+'</div></body></html>',subtype='html')
