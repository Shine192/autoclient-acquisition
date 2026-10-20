# Architecture — v0.4.0

`delivery.py` adds SQLite outbox/suppressions/events to the same existing state database. Commands use a local file lock; one message is sent per worker tick. A sending claim is committed before Gmail's send POST. Any ambiguous outcome remains held until Sent reconciliation; Message-ID is a search key, not a provider idempotency guarantee. A durable Sent receipt precedes Notion sync.

`gmail.py` uses Google Desktop OAuth with PKCE/state validation and loopback callback, send/read-only scopes, sender verification and owner-only token files. No credentials are bundled. The delivery worker reloads settings and Notion drafts before dispatch. A policy hash binds sender, targeting, offers and limits to approval; changing them invalidates approval.

Incoming text and scraped research never become instructions. Replies conservatively stop outreach and are queued for human review. No model has access to send tools; recipient, mode, approval and routing checks run in Python.

See SENDING.md and VALIDATION.md for setup, test limits and recovery. Discovery architecture follows.

---

## Discovery and review

## Components

`python3 -m acquisition_agent` is the entry point. A synchronous local worker polls Notion every 30 seconds. Python's standard library supplies HTTP, SQLite, RSS parsing and file handling. Configuration lives separately from code.

1. **Discovery:** public RSS and optional paid web search. Search is off by default. RSS alone is a narrow source, not comprehensive coverage of all markets.
2. **Research:** retrieve original page text, check robots rules, strip scripts/styles and retain source URL. No CAPTCHA, login or paywall bypass. HTTP content is data, never executable agent instructions.
3. **Matching:** transparent heuristic checks for email/Klaviyo relevance, countries, freelance arrangement, remote eligibility, explicit USD per-email budget, hours and exclusions. Scores rank candidates for review; they do not prove fit.
4. **Drafting:** manual chat handoff or optional API call. AI cannot set recipient routing or approval. The import validator checks lead identity and quotes but is not a factuality proof for every sentence.
5. **State:** SQLite stable source-URL IDs, local flags, session audit details, prompts and drafts. Canonical URLs remove common tracking parameters. Different URLs for the same vacancy/company are not guaranteed deduplicated; cross-source identity and contact-history deduplication are future work.
6. **Notion:** first sync creates a row, later sync preserves remote editor changes. Explicitly changed local drafts invalidate approval. A session queue provides a simple command interface.

## Data ownership

- Profile facts originate from Shine's supplied aboutme(1).dm and chat preferences. Portfolio links are recorded; individual works have not been independently reviewed.
- Raw search snippets are not used as researched facts. Direct source text is retained. Company names, headquarters, hiring-contact relevance, posting freshness and source intent still need review when ambiguous.
- Native API adapters use a locally configured token. ChatGPT's existing Notion connection does not supply that token to the worker.
- Runtime files contain personal research and contact data. Keep your local state private. Project ZIP excludes runtime state and keys.

## Conservative defaults

- Gmail sending and optional follow-ups exist behind explicit mode, review, test and policy gates; default mode is draft-only. No recurring system task is installed.
- No API calls without explicit API flags and credentials. Default AI provider is manual.
- Research requests have no provider credentials attached and check public DNS destinations and redirects. This is a basic local guard, not a hardened multi-user crawler; it does not pin DNS addresses against rebinding.
- Notion row approval is one of several delivery gates, not sufficient authorization by itself.
- A single worker obtains an OS file lock. A lock only covers its local state directory, not other machines.
- API calls have timeouts and bounded response sizes. There is no monetary hard budget or automatic provider retry.
- Regions, time zones and budget conversions are not guessed from a company domain. Country text matches are provisional. Source dates may be missing or stale.
- Notion polling checks session status between research/draft operations. Already-started requests may complete after a pause.

## Remaining work

Live Gmail OAuth token exchange and send/reply validation; stronger contact/company identity resolution across sources; richer company/contact extraction; recipient-local scheduling; recurring runs; spend reporting; cloud hosting; optional notifications. Source adapters, external provider access and live Notion sync must be verified on the actual connected Mac before relying on unattended runs.

## Local control panel

`panel.py` serves fixed local assets and authenticated JSON endpoints on 127.0.0.1. A temporary bootstrap secret becomes an HttpOnly SameSite cookie; mutations require the matching Origin and CSRF token. Host checks reject DNS rebinding attempts. Secrets are not returned. Source text is rendered as text, not HTML; links allow only HTTP(S). This is a single-user local tool, not an internet-facing service.

The panel reuses the existing Store, draft validator, discovery and Notion synchronization. A single research executor and shared worker lock serialize panel sessions with the discovery worker. Task outcomes persist; interrupted tasks require inspection before retry. Draft saves preserve source evidence, reject contacted/terminal records and invalidate Notion approval. Targeting edits invalidate the approved sending-policy hash. Sending remains controlled by the separate delivery CLI; the panel cannot dispatch or enable automatic mode.
