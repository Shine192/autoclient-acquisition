"""Prepare sourced review facts in Notion; never decide approval for the owner."""
from . import delivery, review
from .providers import rich, research_notes


def prepare(store, notion, lead, config, profile, prefs, exclusions):
    current = delivery.remote_lead(store, notion, lead, persist=False)
    if current.get('status') in delivery.STOP | {'Sending', 'Sent'}:
        return current
    if any(x['lead_id'] == lead['id'] and x['state'] in ('sending', 'sent', 'uncertain')
           for x in delivery.rows(store)):
        return current
    facts = review.sourced_candidate(current)
    _, result = review.evaluate(store, facts, config, profile, prefs, exclusions)
    facts['score'] = result['score']
    issues = result['blockers']
    check = 'Needs information' if issues else 'Ready for review'
    summary = ('Research checks: ' + ('; '.join(issues) if issues else
               'Passed source, contact, draft, fit and timezone checks.') +
               '\nCompany: ' + facts.get('company', '') +
               '\nRecipient: ' + (facts.get('email') or 'Missing appropriate published contact') +
               '\nCompany timezone: ' + (facts.get('company_time_zone') or 'Unverified') +
               '\nOffer: ' + config['offers']['paid_test']['scope'] +
               '\nFinal step: review the recipient, message and contact purpose; set STATUS to Approve. ' +
               'Use Needs Review to hold or Do Not Contact to stop. ' +
               'Approval covers the visible initial email plus ONE no-reply follow-up after two business days. Any reply stops it; the reply draft stays for your review. '
               'Approval does not confirm a vacancy, client interest or work authorization.')
    if config.get('delivery_backend')=='github':
        summary += '\nDelivery: GitHub monitors STATUS=Approve. The Mac can sleep after sync. Company-local windows and daily limits apply.'
    elif result['setup_blockers']:
        summary += '\nSender setup: ' + '; '.join(result['setup_blockers'])
    if facts.get('kind') == 'Cold Outreach':
        from .outreach_copy import observation
        summary += ('\nPersonalization basis: ' + (observation(facts) or
                    'No short source quotation available; review the saved evidence before approving.') +
                    '\nRelevant offer: ' + ('Figma email designs from your client briefs and brand guidelines.'
                    if facts.get('type') == 'Agency' else 'Figma email designs from supplied copy, assets and brand guidelines.') +
                    '\nInterpretation: published services/products establish relevance only. Hiring, interest, budget and workload are unknown unless separately evidenced.')
    props = {'Research Check': {'select': {'name': check}},
             'Review Summary': {'rich_text': rich(summary)},
             'Match Score': {'number': result['score']},
             'Research Notes': {'rich_text': rich(research_notes(facts))},
             'Contact Source URL': {'url': facts.get('contact_source_url') or None}}
    from .simple_workflow import properties
    sequence_page=notion.request('pages/'+facts['notion_page_id'],'GET')
    if not sequence_page['properties'].get('Sequence Mode',{}).get('select'):
        props.update(properties(facts,profile))
    if facts.get('email'):
        props['EMAIL'] = {'email': facts['email']}
    if facts.get('company_time_zone_verified') and facts.get('company_time_zone_source'):
        props.update({'Company Time Zone': {'select': {'name': facts['company_time_zone']}},
                      'Company Time Zone Verified': {'checkbox': True},
                      'Company Time Zone Source': {'url': facts['company_time_zone_source']}})
    # These are findings, not human attestations. Never set STATUS=Approve or
    # any review checkbox here, and never replace a subject/body edited in Notion.
    notion.request('pages/' + facts['notion_page_id'], 'PATCH', {'properties': props})
    facts['research_check'] = check
    facts['review_summary'] = summary
    store.save(facts)
    return facts
