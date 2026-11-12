"""Non-authorizing diagnostics shared by the hosted queue and review UI."""
import re
from . import delivery


def pricing_issue(lead, preferences):
    body = (lead.get('draft') or {}).get('body', '')
    match = re.search(r'(?:USD\s*|\$)(\d+(?:\.\d+)?)\s*[-–—]\s*\$?(\d+(?:\.\d+)?)\s*(?:USD\s*)?(?:/|per\s+)email', body, re.I)
    if match and [float(match[1]), float(match[2])] != list(preferences['design_rate_usd']):
        return 'Draft per-email price differs from configured Figma design range; confirm pricing before approval'
    return ''


def blockers(store, lead, config, profile, preferences, exclusions):
    return delivery.gate_errors(store, lead, config, profile, preferences, exclusions)


def message(issues):
    return 'Approved but blocked:\n' + '\n'.join('- ' + issue for issue in issues)
