# Research on demand, approve in Notion, send in company time

## System 1: research and drafting

Open the Mac dashboard, choose country/city, company type, industries and the
number of prospects. Start Automatic research. The researcher reads official
sources, records quotations, writes a personalized message, and syncs to the
existing Outreach Management System. Draft/Needs Review never authorizes mail.

The original Mac installation and its state stay available. A separate research
CLI can reuse that installation's configuration and keys with a workspace state:

```sh
python3 -m acquisition_agent.research_cli --installation /absolute/path/to/existing-agent --state-dir /absolute/path/to/research-state --country "United Arab Emirates" --city Dubai --company-type Agency --limit 3
```

No credentials belong in command arguments or source. The CLI checks the search
key before spending credit. A 401 requires replacing the key through the existing
Configure-Automatic-Research.command. It does not purchase credit, switch provider
accounts or retry rejected keys. The original dashboard uses its existing keys.

## System 2: individual Notion approvals

The owner explicitly requested this mode on 21 October 2026. Enable once with
`enable-approvals` and the current tested policy hash. This supersedes the dated
pilot's campaign requirement. It retires unattempted campaign queue entries so
current Notion approval can be evaluated under the new mode. Old campaign history,
receipts, contact reservations, suppressions and daily counts remain intact.

After activation there is no campaign target, start date or expiry to maintain:

1. Review company, contact, source, timezone, subject and body in Notion.
2. Set the actual STATUS property to Approve whenever ready.
3. The hosted sender imports qualifying approvals on its next check.
4. It sends Monday–Friday, 08:00 inclusive to 11:00 exclusive in the selected
   company IANA timezone. Approval outside the window waits for the next window.
5. A positive Gmail receipt is saved durably before Notion becomes Sent.

Five approvals today, three tomorrow, and ten next week need no new sender setup.
The maximum remains 50 attempts per Bangkok calendar day, with three-minute
spacing. Pending items carry forward. Follow-ups remain disabled. Replies,
rejections, bounces, opt-outs, closed rows and Do Not Contact stop outreach.
Invalid contact evidence, missing location eligibility for advertised jobs,
or a changed queued message remains visible as a hold requiring correction.

To stop one unsent message, change Approve to Needs Review or Do Not Contact.
To pause everything, run pause or switch SHINE_DELIVERY_ENABLED to false.
Changing a Sent row back to Approve never authorizes another initial email.

## Timing and capacity

GitHub runs while the Mac sleeps. Its cron requests checks every five minutes,
but GitHub can delay or drop them. This implementation checks the real company
time immediately before dispatch. A missed window waits until the next weekday;
it cannot promise dispatch at 08:00 or guarantee same-day completion.

This encrypted Git ledger retains its existing 200-record-per-kind / 900 KB
capacity guard. No history is deleted to extend it. For larger ongoing use,
move the ledger to the planned Cloudflare D1 implementation.

## Verification and recovery

Local tests cover three independently approved messages on different days and
weeks, source and portfolio validation, timezone/weekend rules, final approval
withdrawal, daily limits, atomic duplicate protection, ambiguous Gmail delivery,
Notion receipt retries, reply stops, and research JSON longer than 19,000 chars.

Use status to inspect delivery_model=notion-approval, configuration_ready,
queued, uncertain, notion_sync_pending and actual schedule events. A manual run
does not prove timer cadence. A successful workflow alone is not an email receipt.
Never reset the ledger or retry an uncertain attempt as a new message.
