# Errors & activity

Open **Errors & activity** in the Mac dashboard. It combines local task failures,
current Notion holds, and the hosted sender's private incident history. Each
incident explains the affected step, what happened, a likely cause, its impact,
the easiest next action, an alternative, and how to verify the fix. Causes are
guidance, not a claim that every failure has already been diagnosed.

Filter by company, step, source, and open/resolved status. Related Notion records
and GitHub runs have direct links. **Copy diagnostic details** and **Export safe
diagnostic details** produce a report without API keys, email bodies, provider
response bodies, or stack-local variables. Unexpected exceptions can include
their application module, function and line number for investigation.

## Refresh and history

Saved local information opens immediately. While this section is visible, it
reads current sources about once a minute. **Refresh all sources** performs the
same read immediately. Source labels show the last successful read. Failed reads
preserve cached history and do not mark its incidents resolved. A monitoring
connection failure does not itself mean the sender stopped.

Repeated observations of the same issue remain one incident. A successful check
resolves only the condition it actually checked; a failed or skipped check cannot
prove a fix. Old task imports are processed once and in time order, so a past
failure cannot reopen after a successful retry. Local and hosted histories each
retain up to 200 recent incidents, prioritizing unresolved issues.

History begins with this release. Current visible Notion failures and recent
local tasks can be imported; missing historical events cannot be reconstructed.
Waiting for company-local sending hours, spacing, or the daily ceiling is normal
waiting, not a bug. Replies and opt-outs stopping follow-ups are expected controls.

## Connections and safeguards

The Mac uses its existing Notion connection. Hosted monitoring reads the existing
encrypted `shine-delivery-state` branch through the user's existing GitHub CLI
sign-in. The installer places the existing ledger key in
`state/credentials/error-center-ledger.key` with private file permissions. The key
and caches must never be committed. No new account or paid service is needed.

Monitoring endpoints require the same local session and request protection as
the rest of the dashboard. Refreshing does not send messages, change approvals,
edit Notion, retry delivery, or modify the hosted ledger. The hosted worker itself
adds bounded, sanitized incident history to that encrypted ledger during normal
runs. It does not print incident content into public Actions logs.

Unknown send outcomes require reconciliation of the original attempt. A failed
Notion receipt sync requires retrying that sync, not resending the email. Source,
recipient, duplicate, suppression, price, approval and follow-up checks remain
unchanged. Logging does not supply approval or unlock a held record.
