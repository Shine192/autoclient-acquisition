# Validation — 2026-10-18, v0.4.0

Executed on Python 3.9.6 on the local Mac workspace.

- `python3 -m unittest discover -s tests -q`: 119 tests passed (45 discovery/core, 51 delivery, 3 desktop OAuth and 20 local-panel tests).
- Offline starter import: 3 researched leads and 3 evidence-validated personalized drafts loaded without errors.
- Default outbox is empty; `send-once` in draft-only mode returns without network access or credentials.
- Launcher syntax checked using `zsh -n Start-Agent.command`.
- Notion's existing data source fetched before extension; existing properties/statuses preserved. Added 13 missing review/delivery fields, then fetched again to confirm them.
- The connected Gmail account was checked separately; this does not establish a working local Desktop OAuth token.

The offline suite exercises fake Gmail and Notion adapters, not real email delivery. It covers success receipts and status synchronization, edited draft/recipient holds, original source quotations, portfolio checks, disabled free offers, explicit job route, global pause, source recheck failures, closed vacancies, unknown applicant eligibility, existing Gmail correspondence, per-day caps and Bangkok scheduling, process locks, company/recipient deduplication, stable identifiers, send timeouts, crash recovery, safe reconciliation, preflight retries, threaded follow-ups, reply/new-thread-reply cancellation, bounce/opt-out suppression, and inbound scan failure.

Unverified or intentionally unavailable:
- Desktop OAuth token exchange, refresh and live Gmail send/reply round trip: Google setup and consent were completed, but workspace network policy blocked oauth2.googleapis.com. No local token was saved.
- Live external delivery, recipient spam placement, real delivery reports, multi-contact replies and threading: requires a supervised pilot after the self-test. Gmail acceptance is not inbox delivery.
- Optional paid search/AI APIs: no keys available in this workspace; manual handoff works.
- Hosted always-on execution, recipient-local scheduling, automatic portal application, automatic negotiation, public multi-user OAuth verification: not implemented.
- Outreach permissibility: per-country/context review is required; no universal compliance determination is made by the code.

No production email was sent, no recurring system task installed, and no new paid dependency added. Google Cloud project creation was initially held by approval review; after Shine explicitly approved it, project shine-job-agent was created and Gmail API enablement verified.

OAuth setup update: Google Cloud project shine-job-agent exists; Gmail API enablement and OAuth app configuration were verified in the UI. The approved User Data Policy was accepted, one test user was saved, and a Desktop client was created. Its JSON is stored locally with owner-only permissions. No mailbox token was saved and no email sent. A manual-browser fallback and three OAuth state/PKCE/account-identity tests were added after automatic browser launch failed in this environment.

Local panel: authenticated loopback HTTP integration tests cover bootstrap cookies, Host validation, Origin/CSRF checks, route restrictions, pause/resume, source/draft review, portfolio validation, terminal-state edit holds, preferences and source-grounded imports. Browser review confirmed the rendered pipeline. JavaScript syntax and Python compilation passed. No send or automatic-enable HTTP endpoint exists.

## v0.5.0 discovery update — 18 October 2026

126 automated tests pass after adding additive-source configuration, same-host research limits, explicit opportunity typing, separate source evidence, pause handling, inaccessible-page rejection and pre-fetch domain exclusions. The v0.4 self-test verifier fix is retained. Shine’s screenshots separately demonstrate successful local Notion sync, Gmail authorization, a self-inbox send and reply verification. Production provider Message-ID rewriting, uncertain-send reconciliation and follow-up threading still require an audit; self-test verification alone does not establish those controls.

Live v0.5 cold-watchlist smoke check in the build workspace: all three source hosts failed DNS resolution. Result: zero leads, three explicit source errors. Successful live retrieval through the standalone local worker remains unverified. No blocked-source bypass or synthetic lead fallback was used.

## v0.6.0 validation

135 automated tests pass, including actual provider-reference follow-up threading, metadata failures after confirmed sends, exact Sent-receipt reconciliation, mismatch holds, combined-worker manual mode, persisted discovery intervals, preserving updates and active-worker installation refusal. JS and launcher syntax checks pass. Browser inspection confirmed the v0.6 readiness display on an isolated empty test state. This does not claim the update is installed in the connected Downloads copy or that external production sending, updated feeds or a modern Python runtime have been live-tested.
