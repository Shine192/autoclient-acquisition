# Individually approved follow-ups — 20 November 2026

Full local suite: 443 tests, including 11 new follow-up regressions. Provider and
mail operations are mocked. No live outreach or self-inbox message was sent.
JavaScript syntax and diff whitespace checks pass.

Coverage includes separate initial/follow-up approval; Reviewed does not send;
changed drafts, recipients and source evidence; original receipt and thread;
five/seven business days and second-stage prerequisites; replies and suppression;
unrecorded manual sends; unreadable inboxes; uncertain provider outcomes without
retry; website links in new follow-ups while initial links stay intact; activation
requires the verified current approval policy. Existing suite covers daily caps,
company-local windows, atomic claim, approval withdrawal, receipt-sync recovery,
qualification, selected pricing and acquisition funnel denominator calculations.

Live installation retains a backup, credentials, SQLite/history and local
draft-only mode. Notion review options were extended without approving or editing
any prospect message. The separate owner activation switch cannot authorize any
individual follow-up. No unattended follow-up generation has been enabled.

Limit: a reply arriving between the final inbox read and the provider's send
cannot be eliminated transactionally. Manual receipt reports never count as a
provider-verified prerequisite for hosted second-stage delivery.
