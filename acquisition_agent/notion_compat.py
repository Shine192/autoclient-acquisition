"""Original Outreach Management System boundary; existing fields stay intact."""
from copy import deepcopy
from urllib.parse import urlparse

SOURCE = '30d35189-9d8d-810b-ab15-000b34956275'
DATABASE = '30d35189-9d8d-819b-aac0-ce09ca716b32'
ALIASES = {'Name':'NAME', 'email SUBJECT':'SUBJECT', 'email body':'BODY',
           'sent time':'SENT TIME', 'Company Time Zone':'Time Zone'}
REQUIRED = {'NAME':'title','SUBJECT':'rich_text','BODY':'rich_text','STATUS':'select',
            'COUNTRY':'select','Time Zone':'select','EMAIL':'email','WEBSITE':'url','Type':'select'}


def original(properties):
    return 'NAME' in properties and properties.get('STATUS',{}).get('type', 'select' if 'select' in properties.get('STATUS',{}) else '') == 'select'


def content(prop):
    return ''.join(x.get('plain_text',x.get('text',{}).get('content','')) for x in prop.get('rich_text',[]))


def country(value):
    value=value.strip()
    return {'US':'UNITED_STATES','USA':'UNITED_STATES','United States':'UNITED_STATES',
            'UK':'UNITED_KINGDOM','United Kingdom':'UNITED_KINGDOM',
            'United Arab Emirates':'UAE','UAE':'UAE','Dubai':'UAE'}.get(value,value.upper())


def encode_props(properties):
    result={}
    for key, prop in deepcopy(properties).items():
        if key=='STATUS' and 'status' in prop:
            prop={'select':prop['status']}
        elif key=='COUNTRY' and 'rich_text' in prop:
            value=country(content(prop));prop={'select':{'name':value} if value else None}
        elif key=='Type' and (prop.get('select') or {}).get('name')=='Start-up':
            prop['select']['name']='Startup'
        result[ALIASES.get(key,key)]=prop
    return result


def decode_props(properties):
    result=deepcopy(properties)
    for canonical, actual in ALIASES.items():
        if actual in result:result[canonical]=result.pop(actual)
    if 'select' in result.get('STATUS',{}):
        prop=result['STATUS'];result['STATUS']={**prop,'type':'status','status':prop.get('select')};result['STATUS'].pop('select',None)
    if 'select' in result.get('COUNTRY',{}):
        value=(result['COUNTRY']['select'] or {}).get('name','')
        result['COUNTRY']={'type':'rich_text','rich_text':[{'type':'text','text':{'content':value}}] if value else []}
    return result


def encode_filter(value):
    value=deepcopy(value)
    if not isinstance(value,dict):return value
    for group in ('and','or'):
        if group in value:value[group]=[encode_filter(x) for x in value[group]]
    if 'property' in value:
        key=value['property'];value['property']=ALIASES.get(key,key)
        if key=='STATUS' and 'status' in value:value['select']=value.pop('status')
        if key=='COUNTRY' and 'rich_text' in value:
            value['select']={k:country(v) if isinstance(v,str) else v for k,v in value.pop('rich_text').items()}
    return value


def host(value):
    value=(value or '').strip()
    if not value:return ''
    try:return (urlparse(value if '://' in value else 'https://'+value).hostname or '').lower().removeprefix('www.')
    except ValueError:return ''


def contact_match(page, lead):
    p=page.get('properties',{})
    address=(p.get('EMAIL',{}).get('email') or '').strip().casefold()
    website=host(p.get('WEBSITE',{}).get('url'))
    return bool((address and address==(lead.get('email') or '').strip().casefold()) or
                (website and website==host(lead.get('website') or lead.get('url'))))
