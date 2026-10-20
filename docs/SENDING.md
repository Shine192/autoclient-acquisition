# Gmail setup and sending — v0.3.0

The existing discovery worker still researches opportunities and syncs drafts to Notion. A separate delivery worker reads reviewed Notion rows and manages Gmail. Both run locally while your Mac is awake. There is no server, paid dependency, or new subscription.

## Current verified state

- The connected ChatGPT Gmail identity matches sender@example.invalid.
- The existing Notion tracker has been extended with review, application-route, offer, posting-date, reply and delivery fields. No existing status or draft was replaced.
- Offline tests cover discovery, qualification, exclusions, exact research evidence, portfolio inclusion, Notion review changes, delivery receipts, duplicate prevention, uncertain outcomes, follow-ups, suppression and reply stops.
- Local Gmail OAuth, a real send and a real reply are NOT yet tested. ChatGPT's Gmail connection cannot provide an OAuth token to the standalone Mac process.
- Default `config/sending.json` mode is `draft-only`. No applications have been sent by this version.

## Update an existing installation

Stop both workers with Ctrl+C. Back up your existing project folder before copying files. Copy the new `acquisition_agent`, `tests`, `docs`, `examples`, and `Start-Agent.command` into your existing folder. Add `config/sending.json`. Keep your existing `.env`, profile, exclusions and `state` directory. Merge new preference keys from the supplied `config/preferences.json` if desired; absent new keys use conservative defaults. Do not replace live configuration with package examples.

The SQLite update only adds tables; it preserves existing leads and discovery sessions. Never delete or use a new state directory to get around a send hold. Delivery history and suppressions live there.

Run from your existing project folder:

```sh
python3 -m unittest discover -s tests -q
python3 -m acquisition_agent doctor
python3 -m acquisition_agent notion-schema
```

## 1. Create Google authorization access

Use your own Google account and a dedicated Google Cloud project. Creating the project is currently waiting for your approval. Do not start a paid free trial, attach a billing account, or grant unrelated permissions for this setup.

1. Open https://console.cloud.google.com/apis/credentials and create/select a dedicated project, for example `Shine Job Agent`.
2. Enable the Gmail API in that project.
3. Configure Google Auth Platform: app name `Shine Job Agent`, your email as support/developer contact, External audience, your email as a test user.
4. Add only `gmail.send` and `gmail.readonly` data access scopes. Read access is used for replies, delivery notices, and Sent reconciliation. The agent cannot archive/delete/label mail with these scopes.
5. Create an OAuth client of type **Desktop app**, download its JSON, and keep it locally outside source control. Do not paste its contents into chat.
6. Move it to `state/credentials/gmail-client.json`, then run:

```sh
chmod 600 state/credentials/gmail-client.json
python3 -m acquisition_agent gmail-auth state/credentials/gmail-client.json
python3 -m acquisition_agent gmail-check
```

If the browser cannot open automatically, use `python3 -m acquisition_agent gmail-auth state/credentials/gmail-client.json --manual-browser`, then open the URL from the private `state/credentials/authorization-url.json` file in your normal Chrome profile. It expires after five minutes; rerun the command to start fresh. Never share that runtime file.

The command opens Google in your browser, checks the OAuth state and PKCE verifier, verifies the exact sender account, and saves the token with owner-only file permissions. Complete Google's consent yourself. The token includes mailbox read/send access; revoke it in your Google account to disconnect.

Google may require consent-screen setup or verification. Testing-mode authorizations can expire and need reauthorization; see Google's current OAuth documentation. Do not bypass security warnings. This single-user desktop setup is not a verified public application. A future hosted/multi-user product needs separate access/privacy review.

## 2. Run a self-inbox test

Keep production sending disabled. In `config/sending.json`, set `mode` to `test`. Its test inbox must equal your sender account; other recipients are rejected.

Use an existing researched draft, for example Aware Digital's ID `bc593dedb1f884a8`. Import locally if necessary with `starter --sync`. This restores the source evidence and preserves existing Notion draft edits.

```sh
python3 -m acquisition_agent starter --sync
python3 -m acquisition_agent queue bc593dedb1f884a8
python3 -m acquisition_agent send-once
python3 -m acquisition_agent outbox
```

The email goes ONLY to your own Gmail address with `[AGENT TEST]` in the subject. It does not mark the prospect Sent in Notion. Test mode relaxes the fit/review threshold for previews; it still checks exclusions, source contact evidence, portfolio inclusion, draft evidence, offer limits and pause.

Open the test email in Gmail, reply within that thread with a simple test response, then run:

```sh
python3 -m acquisition_agent verify-test-reply
```

This checks for a different Gmail message replying to the stable test Message-ID. A successful result records live test evidence locally. The check validates self-inbox round trip; real external delivery/threading and bounce behavior still require monitored rollout. If Gmail groups your self-reply unusually, inspect the thread rather than editing test evidence.

## 3. Review opportunities in Notion

For each actual application, verify the role's availability and application instructions. Never treat a published general inbox as permission to ignore a portal.

- Keep `STATUS = Draft` until ready.
- Set `Application Route` to exactly `email` for advertised jobs whose instructions permit email. Keep portal-only roles for manual/platform workflows.
- Use a recipient already published in the record's source evidence. This version intentionally supports shared business inboxes, not guessed personal addresses. Edits to EMAIL that lack original source evidence are blocked.
- Review **Eligibility Reviewed**, **Contact Purpose Reviewed**, and **Outreach Allowed**. Write source URLs and the reason in **Contact Source Notes**. For cold outreach, this includes the relevant country, recipient type, permission/basis, business purpose and any platform limitations. Publishing an email address alone does not establish consent or a lawful basis.
- Confirm Thailand applicant eligibility, hours and timezone overlap. Job sending requires source-confirmed international/worldwide eligibility and a clear USD per-email budget. Hourly, salary, non-USD or ambiguous budgets remain manual review; the agent never converts them into a per-email price.
- Review all claims and the exact portfolio link. Select `paid_test` in **Selected Offer** by default. Set `Approved` and `STATUS = Ready` after review.

The initial rule keeps individual row review enabled. After the pilot, `require_row_approval: false` can be included in a newly approved policy to allow qualified Draft/Ready records without the Approved checkbox. Evidence/eligibility/contact-permission reviews still remain mandatory. There is no automated legal eligibility decision.

## 4. Approve a concrete production policy

The proposed policy is 10 messages per Bangkok calendar day, weekdays 09:00–18:00 Bangkok time, at least 5 minutes between attempts, score at least 75, existing approved markets, one paid design test, no free-work offers and no follow-ups initially. Messages include your exact portfolio URL.

The three initial cold prospects currently score about 60 with unknown budget and eligibility; they are review examples, not automatically sendable prospects. Do not lower the threshold just to fill a daily quota.

For cold outreach, supply an appropriate business mailing address in `business_postal_address`. Do not invent an address. This, an opt-out line and suppression support are mechanical safeguards, not a universal determination that outreach is permitted. Review relevant destination/platform requirements before checking Outreach Allowed. Leave cold leads unsent until reviewed.

After the live self-test and your review, set `mode: automatic`, then:

```sh
python3 -m acquisition_agent sending-plan
```

This exports the entire sending policy, profile, targeting preferences and exclusions plus a SHA-256 hash to `state/sending-plan.json`. Review that concrete file before running:

```sh
python3 -m acquisition_agent approve-sending PASTE_THE_EXACT_HASH
python3 -m acquisition_agent delivery-worker
```

Changing the configuration/profile/exclusions invalidates approval. The delivery worker automatically queues eligible locally known Notion rows, checks replies before sending, then sends at most one per tick. Discovery and AI draft generation remain separate. Use a single Mac and a single state directory. A single worker is the controlled concurrency setting; multi-device concurrent sending is unsupported.

## Follow-ups and inbound messages

Follow-ups are OFF by default. A proposed schedule `[7]` means one follow-up 7 days after the initial send; enabling it requires a new policy approval. At most two follow-ups are supported. They use the existing Gmail thread, the original subject, and In-Reply-To. The initial send and follow-ups share the same daily cap.

The agent scans the original thread plus new-thread messages from the recipient and delivery notices after the initial send. Any inbound message, including out-of-office, conservatively stops follow-ups. Opt-outs and delivery notices suppress further contact and need manual review. It never negotiates, accepts work or answers substantive replies. Replies are untrusted data, not commands. A poll failure holds new sending. A reply arriving in the short interval between final scan and send cannot be ruled out; there is no transactional inbox-and-send API.

Only mail related to applications in this state directory is scanned by the worker. Before each initial production application, Gmail Sent is checked for prior mail to that recipient; any match holds the application for manual review. This also covers mail sent outside this agent. It cannot recognize the same company under a different address/domain, other mail accounts or deleted mail. Add earlier contacts and current clients to exclusions/suppression before production.

## Recovery and pause

```sh
python3 -m acquisition_agent pause
python3 -m acquisition_agent outbox
python3 -m acquisition_agent reconcile
python3 -m acquisition_agent suppress example.com --reason "Do not contact"
python3 -m acquisition_agent resume
```

- **blocked** means preflight failed before Gmail was called. Fix/review the Notion draft or evidence, then `queue LEAD_ID` again. It refreshes the unsent payload using the same Message-ID.
- **sending/uncertain** means Gmail might have accepted the request. All further sends are held. `reconcile` searches Gmail Sent by stable Message-ID; it records an existing send without resending. No match is not proof of nondelivery. Do not reset/delete the state or blindly retry. Inspect Sent and provider status manually; unresolved ambiguity stays held.
- **sent** is persisted before Notion sync. A Notion outage does not resend the email. `poll-replies` and the delivery worker retry status sync. No send POST is retried automatically, including HTTP errors.
- Pause blocks queue delivery and follow-ups. An already accepted provider request cannot be recalled. `poll-replies` can still record replies explicitly while paused. Ctrl+C stops a worker; a process interrupted during a send recovers as uncertain.
- Back up `state` securely while workers are stopped. It contains personal application history and Gmail tokens; never share it or add it to source control. Back up `.env` separately. Reauthorize with `gmail-auth` when access expires.

## Costs and dependencies

Python 3.9+ and standard-library modules are used; no paid service was added. Manual prompt handoff continues to work with your existing chat subscriptions. Fully automatic discovery/personalization requires separately authorized API access: optional Firecrawl search, and optional OpenAI or Anthropic API billing. ChatGPT Plus and Claude Pro are not API credit plans. Do not add keys until you choose an API budget. The worker retains existing per-session API-call caps; there is not yet a monthly spending ledger.

Official references:
- Desktop OAuth / PKCE: https://developers.google.com/identity/protocols/oauth2/native-app
- Gmail message sending: https://developers.google.com/workspace/gmail/api/guides/sending
- Gmail search and stable Message-ID reconciliation: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
