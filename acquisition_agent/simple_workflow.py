"""One visible Notion review approves an exact initial/no-reply message pair."""
import hashlib,json,re
from .commercial import OUTREACH_PORTFOLIO,DEFAULT_QUOTE
MODE='Main + one follow-up'

def automatic_quote(documents):
    """Unknown size uses the lower quote; never invents headcount or client budget."""
    for d in documents:
        text=d.get('text','')
        match=re.search(r'\b(\d{1,5})(?:\s*[-–]\s*(\d{1,5}))?\s+(?:employees|staff members|team members)\b|\bteam of\s+(\d{1,5})\b',text,re.I)
        if match:
            count=int(match[1] or match[3]);label='USD 30–35/email' if count>50 else DEFAULT_QUOTE
            return label,('Offered quote based on published team-size wording: '+match[0]+'. Source: '+d.get('url','')+'. Not a confirmed client budget.')
    return DEFAULT_QUOTE,'Employee count unknown. Conservative offered quote USD 25–30/email; no headcount or client budget inferred.'

def followup_body(company,signature='Shine'):
    return ('Hi '+company+' team,\n\nFollowing up on my freelance email design enquiry. I would be happy to discuss a small paid test if you need Figma design or Klaviyo production support. If the timing is not right, no problem.\n\n[View my portfolio]('+OUTREACH_PORTFOLIO+')\n\nThank you,\n'+signature)

def reply_body():
    return ('Thank you for your reply. Could you share the email design or Klaviyo scope, supplied copy/assets, and preferred timing? I can review the requirements and confirm pricing and availability before we agree on any work.\n\nShine')

def properties(lead,profile):
    from .providers import rich
    if not lead.get('draft'):return {}
    return {'Sequence Mode':{'select':{'name':MODE}},
            'Follow-up 1 Draft':{'rich_text':rich(followup_body(lead.get('company',''),profile.get('preferred_name','Shine')))},
            'Follow-up 1 Review':{'select':{'name':'Draft'}},
            'Follow-up 1 Delivery':{'rich_text':rich('Included in your initial sequence review. Sends once after two company-local business days, only without a reply.')},
            'Reply Draft':{'rich_text':rich(reply_body())},
            'Reply Draft Status':{'select':{'name':'Template — review after reply'}},
            'Pricing Reason':{'rich_text':rich(lead.get('pricing_reason','Selected offered quote; client budget remains separate.'))}}

def snapshot(p):
    from .providers import text_value
    if (p.get('Sequence Mode',{}).get('select') or {}).get('name')!=MODE:return None
    fields=['email SUBJECT','email body','Research Notes','Contact Source Notes','Application Route','Follow-up 1 Draft']
    value={k:text_value(p.get(k,{})) for k in fields}
    value.update(recipient=p.get('EMAIL',{}).get('email'),quote=(p.get('Design Quote',{}).get('select') or {}).get('name'),
                 portfolio=p.get('Portfolio Link',{}).get('url'),timezone=(p.get('Company Time Zone',{}).get('select') or {}).get('name'))
    if not value['Follow-up 1 Draft']:raise ValueError('Prepare the no-reply follow-up before approving the sequence')
    return {'hash':hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),'followup':value['Follow-up 1 Draft'],'business_days':2,'maximum_followups':1}

def apply_quote(body,label):
    low,high=(25,30) if label==DEFAULT_QUOTE else (30,35)
    pattern=r'(?:USD\s*\$?|\$)\d+(?:\.\d+)?\s*[-–—~]\s*\$?\d+(?:\.\d+)?\s*(?:USD\s*)?(?:/|per\s+)email'
    value='USD '+str(low)+'–'+str(high)+' per email'
    if re.search(pattern,body,re.I):return re.sub(pattern,value,body,flags=re.I)
    return body+'\n\nFigma design: '+value+'. Klaviyo implementation quoted separately.'
