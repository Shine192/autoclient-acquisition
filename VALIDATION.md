# Validation and activation status

20 October 2026. The core sender was merged under Shine192 after 325 offline
tests and GitHub-hosted CI passed. The handover retry fix now passes 332
offline tests. Its GitHub CI is checked on the associated pull request.
Public samples use synthetic identity/contact details. Real Mac settings,
credentials and history are excluded from the public source.

The first user-run handover created a private backup and switched the Mac
sender to draft-only, then stopped before creating a delivery-state branch.
The next attempt encountered GitHub HTTP 403 because the workflow was already
disabled. Setup now accepts that state, verifies state transitions and reports
the failed CLI operation and status without printing credentials or response
bodies. Tests cover a full fixture handover from an already-disabled workflow,
concurrent disable requests, rejected transitions and sanitized errors.

Live checks passed for the new repository identity, permissions, the
already-disabled workflow and one harmless Git blob write containing no
applicant, lead or credential data. No delivery-state branch was created by
these checks. No production or test email has been sent by this update.

Existing state-machine coverage includes competing claims, encryption and
persistence failures, ambiguous Gmail results, Notion receipt failures,
approval changes, eligibility, exclusions, local windows, quotas, campaign
dates and reply/suppression stops. A fixture export preserves old receipts and
counts; guarded live exports never bypass an active Mac lock.

Still unverified: successful live Mac handover, secret/state initialization,
hosted OAuth refresh and Notion sync, self-inbox/reply verification and
production dispatch. The actual Mac mode change was made by the user's
handover command; the workspace has not edited that installation.
Cloudflare remains deferred. Do not describe this sender as activated.

Location validation fix: US California/CA and New York/NY office quotes
accept exact uppercase postal tokens only under a United States state request.
Exact source quotation and observed location/type checks remain required.
Sourced timezone inference also runs for agencies with no brand industry.
California uses America/Los_Angeles. Tests cover missing quotes, substrings,
other countries and unchanged input records. The full offline suite passes
335 tests. Real hosted self-inbox sending and reply verification passed.
Production dispatch remains disabled pending final campaign approval.

Post-campaign tracking: when dates end before the campaign total is reached,
the enabled sender still polls replies on its bounded interval, verifies the
Gmail identity and does not import or send applications outside the dates.
The full offline suite now passes 336 tests.
