# Shine — GitHub-hosted sender update

Decision recorded 20 October 2026: improve the existing GitHub Actions sender
now. Keep the Mac installation for research and drafting. Defer Cloudflare
Workers + D1 to a later product version. No Cloudflare or Google billing setup
is required by this update.

## What this changes

The original repository uses Ready, recipient-local 09:00–17:00, no weekday
filter and no enforced daily cap. It also sends on pushes to main, discards
the paginated results, reads only the first rich-text block, and can duplicate
a send if Gmail accepts it before the Notion status update fails.

This update replaces that entry point while retaining the original script and
workflow under legacy/. It reuses the current research agent's qualification,
source evidence, Notion compatibility, Gmail API, signature and reply checks.

- Final human approval is the actual Notion STATUS = Approve property.
- Weekday company-local 08:00–11:00; IANA timezones handle daylight saving.
- Maximum 50 attempts per Bangkok calendar day; at least 180 seconds apart.
- Explicit campaigns of 1–100 attempts on 1–14 selected company-local weekdays.
- Follow-ups stay disabled in this initial hosted version.
- Appropriate published contact, fit, exclusions and job eligibility checks
  still apply. Portal-only applications stay held.
- Research and drafting remain on demand on the Mac. No OpenAI/Firecrawl keys
  are needed by this sender. It never writes or negotiates substantive replies.
- Notion remains your review interface. Missing evidence remains held.

## Public example configuration

The public config and examples use synthetic identity and contact details.
They are test fixtures, not your production profile. Handover reads your real
profile, signature and settings from the existing Mac installation into the
encrypted ledger; it does not replace them with these examples.

## Durable state and public-repository privacy

The repository is public. Leads, messages, settings and send history are stored
only as an authenticated encrypted ledger on the dedicated shine-delivery-state
branch. The Fernet key is a GitHub Actions secret, backed up privately on your
Mac. Gmail OAuth credentials and the Notion token remain separate secrets.
Do not publish plaintext exports, SQLite databases, keys or tokens.

State is saved through Git blob/tree/commit APIs with fast-forward-only branch
updates. Competing sibling claims cannot both commit. The attempt, campaign
allowance and daily count are committed before Gmail is called. A failed or
ambiguous state update stops the client. Gmail timeouts remain unresolved and
are never blindly retried. A successful Gmail receipt is saved before Notion.
Artifacts and caches are not the authoritative queue.

This is a bounded, occasional-use solution: maximum 200 records per kind and
900 KB encrypted state. Each mutation adds Git history. It is suitable for
your current small campaigns, with more storage/history growth than a real
database. Move to Cloudflare + D1 before expanding substantially; do not delete
history to bypass the pilot limits.

## Deployment status

Source is published; production sending is NOT activated. No production email has
been sent by this update. The transfer to Shine192/autoclient-acquisition was verified on 20 October
2026 (repository ID 1166990339). The connected account is Shine192 and has
repository write access. Never paste credentials into ChatGPT.

## Setup once

1. Publish this source as a branch/PR in the existing repository, review the
   change, run the test workflow and merge it. Replace the existing main.py
   and .github/workflows/outreach.yml with these versions. Keep email_template.html;
   the new sender uses plain text and does not require it.
2. Authenticate GitHub CLI as the owner or an authorized collaborator. It needs
   repository contents/workflow writes, Actions administration, and repository
   secrets/variables writes for the setup command. These are needed only to
   configure this repository; the running workflow uses its own GITHUB_TOKEN.
3. Close the local dashboard and active work. Double-click
   Prepare-GitHub-Handover.command. It disables the old workflow, switches the
   existing Mac sender to draft-only, backs up the SQLite database and sending
   config, and imports the latest history into encrypted Git state. It reuses
   the existing Notion token and Gmail OAuth authorization through secret stdin
   uploads. It preserves the Mac code, research, queue, API keys and files.
   It re-enables the workflow with the global delivery switch OFF and the
   ledger PAUSED. It does not send any email.
4. GitHub → Actions → AutoClient Outreach → Run workflow: choose dry-run.
   Check the approved-record count and policy hash. Review the complete sender,
   targeting, address, offer and rules in the local policy-review.json saved
   by the handover command.
5. Run self-test. Only your own configured Gmail inbox can receive this test.
   Reply in Gmail with its verification line. Run verify-test with the test ID.
6. Run activate with the reviewed policy hash. This is the one-time approval
   for the hosted sender. Per-message approval remains in Notion.
7. Run campaign with the target, such as 20, and company-local dates such as
   2026-10-21,2026-10-22. This starts a NEW hosted allowance; it does not reset
   old daily counts or contact history. Close the existing hosted campaign
   before starting another one.
8. In repository Settings → Secrets and variables → Actions → Variables, set
   SHINE_DELIVERY_ENABLED to true. Confirm the scheduled workflow is enabled.
   The sender now checks approved Notion records periodically. Your Mac can
   sleep after research and syncing finish.

Do not re-enable the Mac's automatic sending while GitHub owns delivery.
Run-Shine can still run research and sync in draft-only mode; delivery status
is now tracked in GitHub/Notion. A local draft-only label is expected.

## Daily workflow

1. Open the original Mac dashboard; choose your audience and search/draft.
2. Wait for successful Notion sync, then close the Mac if desired.
3. Review source evidence, recipient, timezone and message in Notion. Set
   STATUS = Approve for messages you authorize. No extra review checkbox.
4. GitHub imports complete research and queues qualified approved messages in
   the active campaign. It sends only inside the recipient's selected weekday
   window and campaign dates. Scheduled Time is an eligible time, not an exact
   delivery guarantee. Sent/reply metadata returns to Notion.

Existing locally saved research is imported during handover. Future records
need valid structured Research Notes in Notion. Truncated/missing research
stays held; repair and sync from the dashboard rather than inventing it.

## Scheduling, limits and cost

The timer checks every five minutes away from the top of the hour. A run sends
at most two messages, three minutes apart, and exits early when nothing is
eligible. GitHub can delay or drop scheduled runs, so it cannot guarantee a
specific minute. The sender rechecks the actual local time immediately before
dispatch and waits if the window has closed.

Standard hosted runners for a public repository are currently free. Private
repositories have included minutes and possible overage charges. This sender
adds no AI-generation requests. Research API costs on the Mac remain separate.
Disable the delivery variable between campaigns to avoid unnecessary jobs.
Public-repository schedules may be disabled after 60 days without activity;
check the Actions page when starting a campaign after a long break.

## Recovery and pause

Setup accepts an already-disabled workflow. A retry after an early failure
does not try to disable that workflow again. Existing delivery history must
still never be reset or reinitialized.


- Choose pause to hold the ledger, or turn SHINE_DELIVERY_ENABLED off to stop
  future scheduled jobs. An already accepted Gmail send cannot be recalled;
  a manual workflow operation may wait behind the current serialized run.
- If state or secret upload fails, leave the Mac draft-only and delivery OFF.
  Keep the private update-backups/github-handover-* folder. It contains the
  ledger key and old config. Do not rerun initialization over existing state.
- For an incomplete initial setup, finish uploading the SAME backed-up ledger
  key and existing credentials; never generate a replacement key for history.
- For an uncertain outcome, inspect Gmail, then use reconcile with the outbox
  ID. Only a matching positive Sent receipt resolves it. Absence is not proof
  of non-delivery. Do not set it back to queued or delete its reservation.
- Notion failures can be retried after the connection recovers; a saved receipt
  prevents another email. Never change Sent back to Approve to retry.
- Google OAuth tokens can expire/revoke. If the OAuth app is in Testing, its
  refresh-token lifetime may be limited. Reauthorize on the Mac and update the
  Gmail secrets as needed; the sender fails closed while authorization fails.
- To return sending to the Mac, stop hosted delivery and reconcile/import its
  latest history FIRST. Do not simply restore an old SQLite backup or sender
  config, because that would omit newer hosted sends and daily counts.

## Testing

Run: python -B -m unittest discover -s tests -q

Tests use sample opportunities, fake Gmail/Notion and an in-memory Git server.
They cover existing qualification and outreach gates, atomic competing claims,
encrypted-state failures, accepted-but-timed-out ref updates, Gmail uncertainty,
Notion failures after delivery, replies, approvals, timezone windows, campaign
limits, migration and public workflow protections. A real hosted self-inbox
test and production activation still require the one-time handover and setup.

Official references:
- https://docs.github.com/en/rest/git/refs
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://cryptography.io/en/latest/fernet/
