# Validation and current deployment boundary

20 October 2026. The existing Mac installation and deferred cloud version were
not edited. No new external email or paid research request was made. GitHub
repository access checks were read-only. The first publication attempt was
blocked by automatic approval review because sample files contained personal
profile details. Public sample identities, addresses, telephone numbers and
portfolio links were replaced with synthetic values before publication.
The actual Mac profile remains unchanged.

The final offline test result is recorded in validation-summary.json. This
includes the current agent's regression suite plus hosted queue, worker,
Git-state, encryption, migration, approval and workflow tests. Real encryption
is tested with ephemeral keys; Gmail, Notion and Git mutation APIs are fakes.
Action release tag SHAs were verified against the official actions repositories.
Both workflows parse correctly; third-party actions use full commit pins.

Important checks include:

- competing independent Git-state clients have one successful atomic claim;
- the claim and limits persist before a Gmail side effect;
- ref-update timeout after acceptance leaves an unresolved durable attempt;
- a poisoned state client cannot continue sending;
- Gmail timeouts and incomplete receipts do not trigger another attempt;
- Notion update failure after a saved Gmail receipt cannot resend;
- revised drafts and withdrawn approval are held for new Notion review;
- published source, portfolio, exclusions, eligibility and timezone gates;
- weekday/window, spacing, campaign and daily limits;
- old Ready is not new hosted approval;
- self-test routing is only to the configured owner, with verified reply;
- seeded production history reserves prior recipients/companies and daily use;
- read-only GitHub setup fails before modifying the Mac configuration;
- missing remote history cannot implicitly create a fresh queue.

The guarded read-only export check against the real Mac correctly refused to
run while panel.lock was held. It did not bypass the lock or modify the app.
The handover/export is tested against isolated SQLite fixtures; its final live
execution remains pending after authorized repository publishing.

Not yet verified: GitHub-hosted CI, actual branch/secret initialization, hosted
OAuth refresh, live Notion sync, hosted self-inbox/reply test and production
dispatch. These require the one-time handover and deliberate setup.
Do not describe this source package as already activated.

Transfer verified on 20 October 2026: repository ID 1166990339 is now owned
by Shine192. The connected Shine192 account has push=true and admin=true.
Main remains d556f112ce42788f9c6e17efb7ac8c7400b2b699; no delivery-state
branch exists yet. The sender repository binding now uses the new owner.
