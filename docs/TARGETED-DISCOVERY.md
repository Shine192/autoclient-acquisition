# Targeted discovery — v0.7.0

## Your chosen setup

No paid API keys are added. Use your web-enabled ChatGPT session for research and drafting, then paste its JSON into the local panel. The local app does not automate your ChatGPT browser, scrape search results behind access controls, or assume a ChatGPT Plus/Claude Pro subscription includes API access. Automatic sending still uses the approved Gmail policy. It requires approved, qualified Notion records and an awake Mac with the agent running. Follow-ups and free work remain disabled under your current policy.

## Install without replacing your records

Stop the panel and agent with Control+C. Extract this release into a separate folder and run `Apply-Targeted-Discovery-Update.command`. It uses the preserving updater, adds missing Notion review fields, and leaves credentials, saved leads, sending settings and approval intact. No second state directory is created. You can restore changed code from the printed update-backups path. Do not roll back your mailbox records after sending.

Open your existing project and run:

```bash
python3 -m acquisition_agent dashboard --port 8766
```

Open the private URL printed by Terminal. Under Discovery, use **Choose your next client**.

## Daily session

1. Choose a country within the approved markets; enter the target city or region.
2. Choose Brand, Agency or Start-up. Choose one or several industries; an industry is required for brands. For agencies, the industry describes their clients, not their own business classification, and requires source evidence.
3. Choose prospective clients or advertised freelance jobs, and a maximum candidate count (default five, maximum twenty).
4. Click Create research prompt. Copy it into a ChatGPT session with web search enabled. Review the sources in its answer. Fewer matches or an empty result are valid outcomes.
5. Paste the JSON into the matching saved discovery session. Click Import companies + drafts. Stop the background worker before importing; the shared worker lock prevents overlapping discovery/import/sync.
6. Review the task result. If Notion is connected, the importer adds missing fields and syncs. If Notion sync fails, the leads stay saved locally: retry Sync to Notion, not the import. Import does not queue or send. Duplicate companies remain unchanged, including prior contacted records.
7. In Notion verify the actual city, type and industry, not just the requested search filters. Check Targeting Reviewed only when the official evidence supports all three. Verify Company Time Zone, Source and Verified. Complete the existing eligibility and contact-purpose reviews. Review the subject, body, exact portfolio link, offer and scope. Mark Approved and Ready only when suitable.
8. Restart `python3 -m acquisition_agent agent`. Delivery respects the company-local 9–11 AM weekday window, ten total daily emails by Bangkok date, five-minute spacing, exclusions, suppression, source rechecks and duplicate controls. A score alone does not authorize outreach.

## Industries and design ideas

- Chocolate, Snacks & Nuts: appetizing product imagery, seasonal gifts, limited editions and cart reminders.
- Supplements & Nutraceuticals: clear benefits, ingredients, trust and subscriptions; no unsupported health claims.
- Furniture & Rugs: editorial lifestyle layouts, product grids, room pairings and high-ticket cart reminders.
- Fashion & Apparel: collections, lookbooks, flash sales and approved UGC.
- Drinks & Beverages: routines, subscriptions and bundles.
- Gyms & Fitness Centers: schedules, trainers and membership renewals.
- Boxing & Combat Sports Clubs: events, seminars and merchandise.
- Pet Care: booking reminders, friendly imagery and care tips.
- Education Providers & Course Creators: onboarding, webinars, resources and scannable long-form layouts.

These are service suggestions, not evidence that a prospect has a broken flow or needs to hire. Do not claim an audit, signup, revenue loss or poor performance without verified evidence.

## Data and evidence

Session settings are stored in the existing SQLite state under target_sessions. Each new imported lead retains a session ID and snapshot, observed company location/type/industry, exact source quotes, the source documents and draft evidence. Notion adds Discovery Session, Target City, Industry and Targeting Reviewed. Country/type remain in the existing properties. It does not overwrite approval or draft edits on existing records.

Imports retain published shared organizational inboxes from the supplied official page text. Missing, multiple or obfuscated contacts need review; no addresses are guessed. An email's publication does not establish suitability or permission to pitch. The existing pre-send workflow rechecks the actual contact page; a blocked/unavailable page holds sending.

Location quotes must name the requested city/region. Type and industry evidence quotes must appear in the supplied official source documents; industry quotes must mention a corresponding industry term. These mechanical checks do not prove that an AI classification is correct. Targeting Reviewed is a required independent human check before new targeted records can send. No automatic location or timezone claim is inferred from the session choices.

The field match score for these cold prospects measures evidenced service fit. An industry match is not a job vacancy, confirmed budget or willingness to work with an overseas freelancer. Posted jobs retain the existing stricter skill, eligibility and application-route checks.

## Validation and limits

152 offline tests passed, including a local HTTP session creation and batch-import workflow with a synthetic company; no external emails were sent. Tests cover exact portfolio and evidence checks, missing/mismatched city and industry, exclusions, original-host source enforcement, review gates and duplicate preservation. JavaScript and shell syntax checks also passed. Native browser visual verification was blocked because the Mac was locked. Real external research, imported chat output and a production application must still be validated during your first user-selected session. No prospect from the New York example was imported or contacted.

Older Python/LibreSSL can still fail against some sites. Updating the Python runtime is a separate setup task; this release does not disable TLS verification or bypass site restrictions.
