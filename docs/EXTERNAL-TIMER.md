# Delivery timing: prepared, not activated

The GitHub-native five-minute schedule is best-effort. Observed scheduled
runs on 11–12 November 2026 were hours apart. A manual run, cron-expression
change, or successful HTTP dispatch does not prove reliable automatic sending.

## Independent trigger option

An external scheduler such as cron-job.org can request the existing GitHub
worker every five minutes. This removes reliance on GitHub's native schedule
event, but GitHub runner availability is still a dependency. It is an
improvement, not an exact-time delivery guarantee. Keep the native timer as a
backup. The sender's shared concurrency lock and atomic duplicate protection
remain authoritative.

This option starts **inactive**. `SHINE_EXTERNAL_TIMER_ENABLED` permits the
non-sending review receiver. Production `operation=run` additionally requires
`SHINE_EXTERNAL_SEND_ENABLED=true`, a separate explicit activation. Missing or
false switches fail closed. An account and a new repository-scoped credential are required;
never copy a general CLI login token or Gmail/Notion/ledger credentials into a
scheduler. Do not paste credentials into chat, repository files or logs.

## Private setup

1. Create/sign into the chosen scheduler account.
2. Create a fine-grained GitHub personal access token, restricted to
   `Shine192/autoclient-acquisition`, with **Actions: write** and the automatically
   required metadata access. Choose an expiry and record its renewal date.
3. Create an initially disabled HTTP job with:
   - URL: `https://api.github.com/repos/Shine192/autoclient-acquisition/actions/workflows/external-delivery.yml/dispatches`
   - Method: POST
   - Headers: `Accept: application/vnd.github+json`,
     `Content-Type: application/json`, `X-GitHub-Api-Version: 2022-11-28`,
     and an `Authorization` header containing `Bearer ` followed by the new token.
   - Body for the first, **non-sending** check:
     `{"ref":"main","inputs":{"operation":"review"}}`
   - Interval: every five minutes; enable failure notifications in the scheduler.
4. After explicitly approving this setup, set the repository variable
   `SHINE_EXTERNAL_TIMER_ENABLED=true`. Keep `SHINE_EXTERNAL_SEND_ENABLED` absent
   or false, and keep the cron job disabled. Keep its operation as `review`
   for the first execution. Review changes queue/hold diagnostics but sends no
   email and does not approve any Notion row. Native delivery may independently
   process previously approved, eligible rows.
5. Check BOTH the provider's execution history and GitHub's External delivery
   trigger run. A 204 response only means GitHub accepted a dispatch request.
6. Once the result is verified and production scheduling is explicitly approved,
   set `SHINE_EXTERNAL_SEND_ENABLED=true`, change the HTTP body to
   `{"ref":"main","inputs":{"operation":"run"}}` and enable the repeating
   job. Do not use this as a way to bypass row approval or holds.

## Acceptance checks

- Observe multiple consecutive automatic provider executions and corresponding
  GitHub jobs. Manual executions do not establish scheduler health.
- Verify elapsed intervals, including during an actual company-local window.
- Require a saved individual receipt before calling any email sent.
- Do not treat stale/missing run information or a successful dispatch as healthy.
- The existing health report checks the **native** timer only. External
  dispatches remain `workflow_dispatch` events and must not be relabelled as
  genuine native schedule events. Check provider history separately.
- If requests succeed but jobs queue for too long, an independent worker
  platform is needed; increasing dispatch frequency will not solve runner delay.

All sending still requires actual Notion STATUS=Approve, complete evidence,
valid recipient/offer, weekday company-local 08:00–11:00, at most 50/day,
three-minute spacing, and no receipt, reply, suppression or unresolved attempt.
A missed window rolls to the next eligible weekday; it never extends to 11:01.

To stop external sending while preserving non-sending review access, set
`SHINE_EXTERNAL_SEND_ENABLED=false`. To stop all external checks, disable its
scheduler job and set `SHINE_EXTERNAL_TIMER_ENABLED=false`. Do not delete sending history. To stop all
delivery, use the existing delivery switch/pause, not just this external switch.

References: [GitHub scheduling limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
[workflow dispatch permissions](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event),
and [cron-job.org](https://cron-job.org/en/).
