# Expanded discovery — v0.5.0

## What changed

The existing two We Work Remotely feeds remain. An additive `config/discovery.json` adds Remotive's public RSS feed and an editable watchlist of official company or individual job URLs. There is no new local API key, paid dependency, or scheduled run. Existing preferences, Gmail token, Notion key and state are preserved. The v0.4 reply-verification fix is included.

The initial watchlist contains The Orchard Agency, LION Digital and 23 Digital. These are cold prospects, not advertised openings. The Orchard contact page was retrieved during research and publishes a shared organizational inbox; budget, freelance interest and Thailand eligibility are not confirmed. The other two service URLs were found in search and still require successful local page retrieval. Watchlist membership is a research candidate, never proof of qualification or permission to send.

## Install into your existing folder

Stop the local control panel and discovery worker with Ctrl+C. Back up the installation. Replace the entire `acquisition_agent` folder from this release. Add the new `config/discovery.json` file without replacing your existing profile/preferences/exclusions/sending files. Preserve `.env` and `state`, including Gmail credentials and self-test evidence. Restart your control panel on its existing port.

From the existing project folder:

```sh
python3 -m acquisition_agent discover --kind both
python3 -m acquisition_agent sync-notion
```

Use `--kind jobs` for feeds and advertised watchlist posts, or `--kind cold` for company watchlist research only. Discovery and sync do not send messages. Keep `config/sending.json` mode `draft-only`.

The panel's Discovery button runs both sources in manual AI mode. CLI output includes configured source counts, researched candidate count, new records, duplicates, prompts and errors. Counts are not promises of qualified leads. Source failures are visible; no inaccessible page becomes a researched lead based only on a search snippet.

## Add sources

Edit `config/discovery.json`. There can be at most ten additional HTTPS RSS URLs and twenty watchlist entries. For example:

```json
{
  "rss_feeds": ["https://remotive.com/remote-jobs/feed/design", "https://remotive.com/remote-jobs/feed/marketing"],
  "watchlist": [
    {
      "company": "Company name",
      "title": "Freelance email design support",
      "kind": "Cold Outreach",
      "url": "https://company.example/email-services",
      "research_urls": ["https://company.example/contact"],
      "enabled": true
    }
  ]
}
```

The `.example` entry is explanatory only; replace it with actual official URLs. Use `Posted Job` only for a specific advertised vacancy, with its exact title. A careers index or agency service page does not establish a vacancy. Use at most two extra research URLs on the same hostname. They retain their own source quotes. Missing fields stay unknown; multiple published inboxes require review. Exclusions also apply before a company's primary page is fetched.

Remotive source links remain in records. Credit Remotive and preserve its original listing URLs if displaying or sharing its listings. Keep manual discovery infrequent (for example morning and afternoon), rather than repeatedly polling. Source terms: https://remotive.com/remote-jobs/rss-feed and https://remotive.com/remote-jobs/api.

## Limits

A watchlist rechecks supplied pages; it does not autonomously enumerate every agency or discover new URLs. Paid web search remains a separate explicit `--search` option requiring your own billed account. ChatGPT's connected research tools do not provide a search API key to the standalone process.

No new advertised vacancy has been certified as both open and eligible for Shine by this upgrade. An inspected PeoplePerHour role requires platform proposals and mentions custom HTML; it was not added to the email outreach watchlist. Never contact a platform buyer through an unrelated address to avoid its application route.

A successful page request alone does not prove that a job is open, overseas applicants are eligible, or the published inbox accepts freelance pitches. Those checks remain necessary before production approval. Version 0.6 adds provider Message-ID references and exact-receipt recovery; see OPERATIONS.md. Uncertain sends remain held.
