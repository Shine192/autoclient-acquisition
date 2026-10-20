"""Consistent applicant closing; postal/opt-out information remains a separate footer."""
import re

SIGNATURE='Thank you,\nShine\nWhatsapp: (+0) 000-000-0000'


def with_signature(body,profile):
    signature=profile.get('email_signature','').strip()
    if not signature:return body.strip()
    body=body.replace('\r\n','\n').strip()
    if body.endswith(signature):return body
    # Replace a prior closing instead of stacking two signatures.
    body=re.sub(r'\n+(?:(?:thank you|thanks|best(?: regards)?|kind regards|regards)[,!]?\s*\n+)?(?:Demo Designer|Shine)\s*(?:\n+Whatsapp:[^\n]*)?\s*$', '', body,flags=re.I)
    return body.rstrip()+'\n\n'+signature


def with_footer(body,profile,footer):
    body=with_signature(body,profile)
    signature=profile.get('email_signature','').strip()
    if signature and body.endswith(signature):
        return body[:-len(signature)].rstrip()+'\n\n'+footer.strip()+'\n\n'+signature
    return body+'\n\n'+footer.strip()
