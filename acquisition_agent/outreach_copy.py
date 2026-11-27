"""Shared honest, helpful copy guidance; research and recipient gates remain separate."""
import re

PAID_TEST = "If this fits your needs, feel free to reply and we can discuss a small paid test email, with no commitment to ongoing work."
PORTFOLIO_INTRO = "You can review my recent work and learn more about my services here: "

STRATEGY=(
    'COLD EMAIL COPY STRATEGY: Use an honest, helpful, professional tone. '
    'Aim for 90–130 words before the signature, with short paragraphs; clarity matters more than exact length. '
    'Structure: one verified observation → relevant Figma/Klaviyo contribution → portfolio → selected offered price → one interest-based question. '
    'For agency introductions, prioritise Klaviyo/email/retention agencies serving e-commerce; offer support from their client briefs and brand guidelines. '
    'Use one specific sourced service, project or case study to explain why you chose them; no generic praise or personal trivia. '
    'Service fit is not evidence of hiring, purchasing intent, budget or an overloaded team. '
    'Do not diagnose weak emails, missing flows, lost revenue or capacity problems without evidence. '
    'Describe desktop/mobile layouts and editable Klaviyo blocks; use only verified contributions, never invented results. '
    'Offer one small paid Figma test from client-supplied copy/assets, with scope and timing agreed before starting. Klaviyo is separately quoted. '
    'Use a clear subject such as Freelance email design support; never fake Re:/Fwd:, urgency, familiarity or an earlier conversation. '
    'End with ONE low-pressure invitation: '+PAID_TEST+' Do not add another question or ask for a calendar booking in the first touch. '
    'Use the selected quote; company size chooses an offered range, not a claim about client budget. '
    'Introduce the portfolio with: '+PORTFOLIO_INTRO+'[View my portfolio](the exact selected portfolio URL). '
    'Posted jobs follow the real application requirements and route; unsolicited HR work enquiries must remain work enquiries, never sales pitches or advertised vacancies. '
    'A follow-up adds a practical scope detail rather than repeating the first email. One follow-up only after two business days; any reply stops it. '
    'Reply drafts are review-only. Do not promise availability, delivery dates or negotiate terms automatically.'
)


def followup(company,signature,portfolio):
    return ('Hi '+company+' team,\n\nFollowing up on my email about freelance email design support.\n\n'
            'For one small paid test, I can work from your supplied copy, assets, and brand guidelines to prepare a Figma email with desktop and mobile layouts. '
            'Scope and timing would be agreed before starting. Klaviyo implementation is quoted separately.\n\n'
            +PORTFOLIO_INTRO+'[View my portfolio]('+portfolio+')\n\n'
            +PAID_TEST+'\n\n'+signature)


def observation(lead):
    from .core import canonical_url,normalize
    documents=lead.get('source_documents',[])
    for item in lead.get('draft',{}).get('evidence',[]):
        quote=item.get('quote','')
        if not isinstance(quote,str) or not 12<=len(quote)<=150 or re.search(r'[@<>%$]|guarantee|\broi\b',quote,re.I):continue
        if re.search(r'privacy policy|terms and conditions|copyright|cookie policy|contact us',quote,re.I):continue
        try:url=canonical_url(item.get('url',''))
        except ValueError:continue
        if any(canonical_url(d['url'])==url and normalize(quote) in normalize(d['text']) for d in documents):
            return 'I noticed your website mentions “'+' '.join(quote.split())+'”.'
    return None


def refreshed_intro(lead,profile):
    """Only for unapproved cold drafts; caller must preserve approvals and history."""
    from .commercial import quote_range,OUTREACH_PORTFOLIO
    if lead.get('kind')!='Cold Outreach':raise ValueError('Keep posted-job applications separate')
    if 'work enquiry' in lead.get('application_route','').lower():raise ValueError('Preserve the specifically authorised HR work enquiry')
    first=observation(lead)
    if not first:raise ValueError('A short verified service observation is required; keep the existing draft for review')
    low,high=quote_range(lead.get('design_quote'))
    agency=lead.get('type')=='Agency'
    offer=('I could support your client projects with Figma campaign and flow designs, following your briefs and brand guidelines.' if agency else
           'I could help prepare campaign and flow designs using your supplied copy, assets, and brand guidelines.')
    body=('Hi '+lead['company']+' team,\n\n'+first+' '+offer+'\n\n'
          'I’m '+profile.get('preferred_name','Shine')+', an email designer based in Thailand. I create desktop and mobile layouts and can build approved designs in Klaviyo with editable, reusable blocks.\n\n'
          +PORTFOLIO_INTRO+'[View my portfolio]('+OUTREACH_PORTFOLIO+')\n\n'
          'My Figma design quote is USD '+str(low)+'–'+str(high)+' per email, depending on scope. Klaviyo implementation is quoted separately.\n\n'
          +PAID_TEST+'\n\n'+profile.get('email_signature','Thank you,\nShine'))
    return dict(lead['draft'],subject='Freelance email design support',body=body)
