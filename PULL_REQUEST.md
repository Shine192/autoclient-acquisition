# Send Notion-approved outreach through GitHub with persistent encrypted history

The existing sender can email on every main-branch push, uses Ready and a
09:00–17:00 window without weekday or daily limits, and can resend after a
successful Gmail request followed by a failed Notion update.

Replace its entry point and workflow with the current Notion Approve flow,
company-local weekday 08:00–11:00 scheduling, maximum 50/day, three-minute
spacing and explicit on-demand campaign totals/dates. Reuse the Mac agent's
qualification, sourcing, personalization validation and Gmail reply checks.
Research remains on the Mac. Cloudflare remains deferred.

An authenticated encrypted ledger on a dedicated Git branch persists claims,
quotas, suppression and receipts before/after dispatch. Fast-forward-only
updates reject overlapping claims; missing or ambiguous state blocks sending.
Public workflow logs do not contain messages, contacts, credentials or HTTP
response bodies. The original SMTP script/workflow are retained under legacy/.

Deployment defaults to paused and requires a user-run Mac handover, hosted
self-inbox/reply verification, approval of the concrete policy, an explicit
campaign and the delivery switch. Merging does not itself send email.

Validation: offline tests for the reused agent and hosted state machine,
including competing claims, persistence timeouts, Gmail ambiguity, Notion
receipt failures, reply/suppression stops, migration, approval, dates and caps.
The transfer to Shine192 is verified and the sender uses the new repository
binding. Hosted CI, the one-time handover and the hosted inbox/reply test
must be completed before production activation.
