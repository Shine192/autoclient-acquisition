"""Non-authorizing diagnostics shared by the hosted queue and review UI."""
import re
from . import delivery
from .core import hostname


# Explicit operator authorization, NOT imported from research or editable
# Notion notes. This changes only the offered design range for this record;
# it never confirms the client's budget, approves a row, or enables delivery.
OWNER_CONFIRMED_OFFERS = ({
    'lead_id': 'fc403920dc3d81fa',
    'notion_page_id': '3ff351899d8d81acaa4afcb9067b3d56',
    'company_host': 'prism-me.com',
    'recipient': 'sales@prism-me.com',
    'kind': 'Cold Outreach',
    'design_rate_usd': (30, 35),
    'confirmed_on': '2026-11-12',
}, {
    'lead_id': '1d9e845f82760645',
    'notion_page_id': '3ff351899d8d81c085bbce1b726db471',
    'company_host': 'irsolutions.tech',
    'recipient': 'hr@irsolutions.tech',
    'kind': 'Cold Outreach',
    'design_rate_usd': (25, 30),
    'work_enquiry_source': 'https://irsolutions.tech/contact-us',
    'work_enquiry_subject': 'Freelance email design and Klaviyo work enquiry',
    'confirmed_on': '2026-11-18',
})


def matching_offer(lead):
    for offer in OWNER_CONFIRMED_OFFERS:
        if (lead.get('id') == offer['lead_id']
                and str(lead.get('notion_page_id', '')).replace('-', '') == offer['notion_page_id']
                and hostname(lead.get('website') or lead.get('url', '')) == offer['company_host']
                and lead.get('email', '').strip().lower() == offer['recipient']
                and lead.get('kind') == offer['kind']):
            return offer
    return None


def published_work_enquiry(lead, document):
    """An owner-selected HR route for this enquiry, never an advertised job."""
    offer = matching_offer(lead)
    if not offer or not offer.get('work_enquiry_source'):
        return False
    if lead.get('application_route', '').strip().lower() != 'unsolicited freelance work enquiry':
        return False
    draft = lead.get('draft') or {}
    if (draft.get('subject') != offer['work_enquiry_subject'] or
            'ask whether you consider remote freelancers' not in draft.get('body', '').lower()):
        return False
    if document.get('url', '').rstrip('/') != offer['work_enquiry_source']:
        return False
    # The exact inbox must follow its jobs label on the official source.
    pattern = r'\bFor Jobs\s+\[?' + re.escape(offer['recipient']) + r'\]?(?:\(|\s|$)'
    return bool(re.search(pattern, document.get('text', ''), re.I))


def offered_design_range(lead, preferences):
    offer = matching_offer(lead)
    if offer:
        return list(offer['design_rate_usd'])
    return list(preferences['design_rate_usd'])


def pricing_issue(lead, preferences):
    body = (lead.get('draft') or {}).get('body', '')
    allowed = offered_design_range(lead, preferences)
    for match in re.finditer(r'(?:USD\s*|\$)(\d+(?:\.\d+)?)\s*[-–—]\s*\$?(\d+(?:\.\d+)?)\s*(?:USD\s*)?(?:/|per\s+)email', body, re.I):
        if [float(match[1]), float(match[2])] != allowed:
            return 'Draft per-email price differs from configured Figma design range; confirm pricing before approval'
    return ''


def blockers(store, lead, config, profile, preferences, exclusions):
    return delivery.gate_errors(store, lead, config, profile, preferences, exclusions)


def message(issues):
    return 'Approved but blocked:\n' + '\n'.join('- ' + issue for issue in issues)
