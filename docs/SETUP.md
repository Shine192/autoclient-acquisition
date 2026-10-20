# Setup on Shine's Mac

## v0.2 quick test

The new launcher option **5** imports three researched agency prospects and personalized draft emails for review. Follow the v0.2 update steps in README. Keep existing credentials and runtime data. This import does not send, use paid AI/search APIs, or prove that an agency is hiring. The companies' published shared business inboxes were checked on 18 October 2026; the contact sources and personalization quotes accompany each record.

The same three starter drafts have been added to Shine's Notion database. Local import uses matching deduplication keys and preserves existing Notion drafts. Use the source pack to bring your Mac's local state into agreement with the review database.

## 1. Test the demo

In Terminal, navigate to the unzipped project folder. Confirm `python3 --version` is 3.9 or newer. Run the four demo commands in README. No installation or paid key is needed.

## 2. Complete your exclusions

Edit `config/exclusions.json`. Enter actual current client/employer names, company domains and prior contact addresses. Domain entries should look like `company.com`, without `https://`. Company names are exact, case-insensitive matches; domains include subdomains. Use domains where a company has several brand names.

Set `confirmed` to `true` after reviewing your list. Until then, each opportunity carries an exclusion-list review flag. Discovery and drafts can still be tested; milestone 1 has no sending capability.

If you want to exclude all previous business contacts, their domains/addresses must be imported here. Inbox history is **not** connected or inferred automatically.

## 3. Run discovery without paid AI

```sh
python3 -m acquisition_agent discover --kind jobs --limit 20
python3 -m acquisition_agent export outputs/leads.json
```

This uses public design and marketing RSS feeds, filters for email design/Klaviyo, then fetches original source pages. A feed may contain no suitable work. Blocked or unavailable pages are reported; they are not bypassed. Research is limited to readable HTML/text, with robots checks for source pages. JavaScript-only pages may provide insufficient text.

For a specific company, replace URL and NAME with a real public company page:

```sh
python3 -m acquisition_agent research-url URL --company NAME --kind 'Cold Outreach'
```

For advertised jobs, use `--kind 'Posted Job'` and supply `--title` if useful. A research page may have no public contact address. The agent does not invent one. If it finds multiple addresses, the email field stays blank for a person's choice.

To import already researched data, provide a JSON array with `url`, `title`, `company`, `kind` (`Posted Job` or `Cold Outreach`), `country` when confirmed, and the actual `source_text`. Optional fields are `website`, `type` and `posted_at`. Do not mark real imports `is_demo`. Contact and budget fields are derived from supplied text rather than accepted as pre-approved routing. Imported source text is user-supplied evidence, not independently fetched proof.

Country detection is deliberately conservative: one explicit target country in the page is a candidate, not verified headquarters. Multiple country mentions or a country missing from the configured list require review. Edit the country list to expand market coverage. No assumption is made that a remote US job accepts a freelancer based in Thailand.

## 4. Use ChatGPT Plus or Claude Pro manually

Discovery generates one `.txt` prompt per lead under `state/prompts/`. Each prompt contains your profile, the source text, the lead ID and the required JSON response shape.

1. Open a prompt, copy its contents into ChatGPT or Claude, and ask for the JSON response.
2. Save the JSON object as `draft.json` in the project folder. Save plain JSON without code fences.
3. Import it:

```sh
python3 -m acquisition_agent import-draft draft.json
```

The program verifies the lead ID, subject, body and exact research quotes. It does not verify every sentence semantically; review the claims, portfolio relevance and tone yourself in Notion. There is no automatic sign-in or browser automation of your paid chat subscriptions.

## 5. Connect Notion

Create a Notion internal integration/connection for this project using Notion's integration settings. Give it read, insert and update content access. Share both the existing acquisition database and the discovery session database with that integration using the connection controls in Notion.

Create a local `.env` by copying `.env.example`. Put the integration token beside `NOTION_TOKEN=`. Do not paste it into this chat. No shell `source` command is required: the application reads simple KEY=VALUE lines itself.

The two data source IDs are already set in `config/preferences.json`. If you use another workspace or copy the databases, replace these IDs with the copied databases' **data source IDs**, not database page IDs.

```sh
python3 -m acquisition_agent doctor
python3 -m acquisition_agent sync-notion
```

After the first sync, Notion is your draft editor. Routine syncs do not overwrite your subject, body, approval or status edits. Importing a new local draft and syncing explicitly replaces its subject/body and clears approval. Closed, suppressed and contacted rows reject draft overwrites. Excluding a previously synced lead marks it Do Not Contact on the next sync.

If a Notion create request times out, retry sync: the agent checks the stable deduplication key before creating another row. The implementation assumes a single Mac/worker; do not run separate state copies concurrently.

## 6. Start discovery sessions from Notion

```sh
python3 -m acquisition_agent worker
```

Open https://app.notion.com/p/48f594c139f443f995d6e4df680501d6. Create a row, give it a name, set Result Limit between 1 and 20, and change STATUS to Queued.

The worker picks it up within approximately 30 seconds, changes it to Running, collects opportunities, prepares prompts, syncs lead rows and reports counts/errors. The session's name is descriptive; discovery parameters come from the local preferences and worker flags, not natural-language interpretation of its name.

In manual mode, Completed means research/prompts were prepared and synced, not that AI drafts were generated or applications were sent. If any source or sync request fails, the session is marked Failed with partial results retained. Inspect Message; failure does not mean every step failed. Resume a failed or interrupted run by setting it to Queued. Duplicates are skipped; use `generate-draft` to retry individual failed API drafts.

Set a running session to Paused to stop between operations. An in-flight HTTP request may finish first. Use Queued to run again. `python3 -m acquisition_agent pause` is a local global pause; `resume` clears it. The worker polls until Ctrl+C or the Mac sleeps. No recurring daily schedule or hosting has been installed.

## 7. Optional separately billed APIs

ChatGPT subscriptions and OpenAI API usage have separate billing. Claude chat subscriptions and Claude API usage are also separate. Usage-based API payment is different from buying another chat subscription. Check the provider's current payment terms and your account before enabling calls; no cost estimate or hard monetary cap is built in.

For automatic drafting, set `AI_MODEL` to a model available in your API account and add the matching API key to `.env`. Then run either:

```sh
python3 -m acquisition_agent discover --ai openai
python3 -m acquisition_agent discover --ai anthropic
```

For cold prospect search across the configured markets, add `FIRECRAWL_API_KEY` and explicitly enable search:

```sh
python3 -m acquisition_agent discover --search --ai anthropic
python3 -m acquisition_agent worker --search --ai anthropic
```

Default limits: 2 search calls, 5 results/query, 20 researched candidates and 10 AI calls/session. Failed AI calls count toward the cap and are not automatically retried. Search queries rotate across US, UK, Europe, Australia and New Zealand, covering jobs, agencies and brands over multiple sessions. Increase `max_search_calls_per_session` to search more markets per session at additional usage cost. These are request limits, not dollar spending guarantees. Configure provider-side spending controls too.

The source imports no provider SDKs; it calls documented HTTP APIs. Models may return invalid JSON or ungrounded drafts, which are rejected or require human review.

## What is next after this milestone?

Authenticate Gmail using a desktop OAuth client and implement self-addressed send testing, approval/version checks, sender verification, daily caps, contact-history suppression, a durable send queue, timeout reconciliation and reply monitoring. Recipient-time-zone scheduling, follow-ups and automatic sending stay out of the current build.

Official references:

- https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform
- https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-is-claude-api-usage-billed-separately-from-my-paid-claude-plan
- https://developers.notion.com/reference/query-a-data-source
- https://docs.firecrawl.dev/api-reference/endpoint/search
- https://platform.claude.com/docs/en/api/messages/create
- https://weworkremotely.com/remote-job-rss-feed
