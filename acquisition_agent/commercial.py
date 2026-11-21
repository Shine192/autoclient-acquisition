"""Owner-controlled quotes and the agency experiment; never grants send approval."""
import copy
import re

QUOTES = {'USD 25–30/email': [25, 30], 'USD 30–35/email': [30, 35]}
DEFAULT_QUOTE = 'USD 25–30/email'
OUTREACH_PORTFOLIO = 'https://shine-email-studio.htooaungshine789.chatgpt.site'
CURATED_PORTFOLIO = 'https://www.figma.com/design/ADkHTEIJLd52MjGcIT1sfX/Portfolio?node-id=9-17'
PAID_TEST_SCOPE = ('One Figma email with desktop and mobile layouts, client-supplied copy and assets, '
                   'and one revision round. Klaviyo implementation is quoted separately. '
                   'Agree turnaround individually; no ongoing commitment.')
PORTFOLIO_CLIENTS = ('Happy Dog', 'Happy Cat', 'Retronanix', 'Tapijtenloods', 'YayNuts',
                     'Candy Festival', 'Creating Home', 'BestfightShop')
EU_COUNTRIES = ('Austria','Belgium','Bulgaria','Croatia','Cyprus','Czechia','Denmark','Estonia',
                'Finland','France','Germany','Greece','Hungary','Ireland','Italy','Latvia',
                'Lithuania','Luxembourg','Malta','Netherlands','Poland','Portugal','Romania',
                'Slovakia','Slovenia','Spain','Sweden')
EXPERIMENT = {'name':'Agency freelance support — first 40', 'target':40, 'weeks':4,
              'review_minutes_per_day':10, 'new_prospect_reviews_per_day':2, 'size_preference':[2,50],
              'regions':{'Australia':10,'UK':10,'Dubai':10,'EU':10},
              'specialty':'Klaviyo/email marketing for e-commerce clients',
              'followup_business_days':[2], 'automatic_followups_enabled':False}


def quote_range(label):
    if label not in QUOTES:raise ValueError('Choose USD 25–30/email or USD 30–35/email')
    return list(QUOTES[label])


def quote_instruction(label=DEFAULT_QUOTE):
    values=quote_range(label)
    return ('Figma design is USD '+str(values[0])+'–'+str(values[1])+' per email. '
            'This is the offered quote, not the client budget. Klaviyo building is quoted separately. '
            'Paid test scope: '+PAID_TEST_SCOPE+' '
            'Use [View my portfolio]('+OUTREACH_PORTFOLIO+') for the website portfolio link when that is the selected URL. '
            'Never name previous portfolio clients in an email; use the portfolio link only.')


def drafting_profile(profile, label=DEFAULT_QUOTE):
    value=copy.deepcopy(profile)
    value['design_pricing']=quote_instruction(label)
    value['paid_test_scope']=PAID_TEST_SCOPE
    value['portfolio_url']=profile.get('curated_portfolio_url') or profile['portfolio_url']
    return value


def profile_for_lead(lead,profile):
    value=copy.deepcopy(profile)
    url=lead.get('portfolio_url')
    if url:
        if url not in (OUTREACH_PORTFOLIO,CURATED_PORTFOLIO,profile.get('portfolio_url')):
            raise ValueError('Prospect portfolio link is not an owner-confirmed portfolio')
        value['portfolio_url']=url
    return value


def portfolio_name_issue(text):
    for name in PORTFOLIO_CLIENTS:
        pattern=r'(?<!\w)'+r'\s*'.join(re.escape(x) for x in name.split())+r'(?!\w)'
        if re.search(pattern,text,re.I):return 'Keep portfolio client names out of email wording; link to the portfolio instead'
    return ''


def region_for(country, city=''):
    if country.upper()=='AUSTRALIA':return 'Australia'
    if country.upper().replace(' ','_')=='UNITED_KINGDOM':return 'UK'
    if country.upper().replace(' ','_') in ('UNITED_ARAB_EMIRATES','UAE') and re.search(r'\bdubai\b',city,re.I):return 'Dubai'
    if any(country.casefold()==x.casefold() for x in EU_COUNTRIES):return 'EU'
    return 'Other markets'


def audience_instruction(spec):
    if not spec.get('agency_focus'):return ''
    return ('Prioritise small agencies offering Klaviyo/email marketing for e-commerce clients. '
            '2–50 employees is a preference, not a hard exclusion; unknown size stays unknown. '
            'Keep service-fit evidence separate from current hiring/purchasing intent. '
            'Capture agency_fit_evidence and business_signal as {url, quote, observed_at, published_at}; '
            'dates and quotations must be published facts or the actual observation date, never invented. '
            'A dated case study proves relevance, not a current need for freelancers. '
            'Record employees only if supported by a public source. Use a suitable business/partnership '
            'route for introductions and a jobs route only for genuine applications or explicit work enquiries. '
            'Never imply a vacancy or budget from a service page. The first experiment targets 10 each '
            'from Australia, UK, Dubai and EU countries; other markets remain available.')


def agency_context(lead, supplied=None):
    """Use exact official passages; an observation date is never a hiring signal."""
    from .core import hostname, normalize, now
    docs=[d for d in lead.get('source_documents',[]) if hostname(d.get('url',''))==hostname(lead['url'])]
    fit=None
    for doc in docs:
        match=re.search(r'klaviyo|email marketing',doc.get('text',''),re.I)
        if match:
            start=max(0,match.start()-60)
            fit={'url':doc['url'],'quote':doc['text'][start:start+300],'observed_at':now()}
            break
    signal=None
    raw=(supplied or {}).get('business_signal',{})
    if isinstance(raw,dict) and isinstance(raw.get('quote'),str) and 12<=len(raw['quote'])<=400:
        for doc in docs:
            if doc['url']==raw.get('url') and normalize(raw['quote']) in normalize(doc['text']):
                # Preserve a published date only when that exact date is in the source.
                date=raw.get('published_at')
                date=date if isinstance(date,str) and date in doc['text'] else None
                signal={'url':doc['url'],'quote':raw['quote'],'observed_at':now(),'published_at':date,
                        'interpretation':'Published business context; freelance demand and budget unconfirmed'}
                break
    ecommerce=any(re.search(r'e.?commerce|shopify|woocommerce|\bdtc\b|webshop',d['text'],re.I) for d in docs)
    return {'agency_fit_evidence':fit or {},'business_signal':signal or {'observed_at':now(),
            'interpretation':'No dated hiring or purchasing signal verified; service fit only'},
            'ecommerce_fit_verified':ecommerce,'employees':None}


def agency_issue(lead):
    if not (lead.get('target_session') or {}).get('spec',{}).get('agency_focus'):return ''
    facts=agency_context(lead)
    if not facts['agency_fit_evidence'] or not facts['ecommerce_fit_verified']:
        return 'Complete official Klaviyo/email-marketing and e-commerce service-fit evidence for this agency audience'
    return ''
