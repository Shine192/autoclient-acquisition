"""Company-local delivery windows; never guess a US timezone from country."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEZONE_OPTIONS = [
    'America/New_York', 'America/Chicago', 'America/Denver',
    'America/Los_Angeles', 'America/Phoenix', 'America/Anchorage',
    'Pacific/Honolulu', 'Europe/London', 'Europe/Dublin', 'Europe/Lisbon',
    'Europe/Paris', 'Europe/Berlin', 'Europe/Amsterdam', 'Europe/Brussels',
    'Europe/Madrid', 'Europe/Rome', 'Europe/Zurich', 'Europe/Vienna',
    'Europe/Prague', 'Europe/Warsaw', 'Europe/Copenhagen', 'Europe/Oslo',
    'Europe/Stockholm', 'Europe/Helsinki', 'Europe/Athens', 'Europe/Bucharest',
    'Europe/Sofia', 'Europe/Budapest', 'Europe/Tallinn', 'Europe/Riga',
    'Europe/Vilnius', 'Europe/Luxembourg', 'Europe/Malta', 'Europe/Zagreb',
    'Europe/Ljubljana', 'Europe/Bratislava', 'Asia/Nicosia', 'Atlantic/Reykjavik',
    'Australia/Sydney', 'Australia/Melbourne', 'Australia/Brisbane',
    'Australia/Adelaide', 'Australia/Perth', 'Australia/Darwin',
    'Australia/Hobart', 'Pacific/Auckland', 'Pacific/Chatham', 'Asia/Bangkok', 'Asia/Dubai'
]


def notion_timezone(prop):
    """Read new dropdowns and preserve compatibility with existing text fields."""
    if 'select' in prop:
        return (prop.get('select') or {}).get('name', '')
    return ''.join(x.get('plain_text', x.get('text', {}).get('content', ''))
                   for x in prop.get('rich_text', []))


def delivery_zone(config, lead=None):
    if config.get('schedule_basis', 'sender') == 'sender':
        return ZoneInfo(config['timezone'])
    lead = lead or {}
    name = lead.get('company_time_zone', '').strip()
    if not lead.get('company_time_zone_verified') or not lead.get('company_time_zone_source', '').startswith('https://'):
        raise ValueError('Verify company timezone and record its public location source before sending')
    if '/' not in name:
        raise ValueError('Use an IANA company timezone, such as America/New_York or Europe/London')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Invalid company timezone; use an IANA region/city identifier') from None


def permitted_time(config, clock, lead=None):
    local = clock.astimezone(delivery_zone(config, lead))
    return local.weekday() in config['send_weekdays'] and config['send_hours'][0] <= local.hour < config['send_hours'][1]
