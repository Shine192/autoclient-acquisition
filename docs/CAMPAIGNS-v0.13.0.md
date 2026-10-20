# Daily ceiling, campaign targets and closing — v0.13.0

## Install into the copy you are currently using

1. Stop the workspace Terminal and any sending workers with **Ctrl+C**. Stop all Shine instances; do not run two installations against the same Gmail account.
2. Extract **Shine-Mac-v0.13.1.zip** alongside your existing app folders and double-click **Update-Existing-App.command** inside the extracted folder. It detects sibling installations containing saved state. With one match, it shows that folder and updates it; with multiple matches, it asks you to choose. Templates and the extracted update itself are excluded.

   The original configured installation currently available is:

   `~/Downloads/autoclient-acquisition/New/shine-acquisition-agent`

   The folder name stays the same; the updated app displays **v0.13.1**. Its existing Gmail connection, settings and records stay there. This patch does not merge state or credentials from removed copies. If the OpenAI/Firecrawl keys were saved only in a different copy, run **Configure-Automatic-Research.command** in the updated installation to enter them privately again.

3. The updater opens the updated dashboard only. Open **Delivery queue** and choose **20**, **30**, **50**, or **Another amount**, then click **Set campaign target**.
4. When ready to run the existing scheduled worker, close the dashboard Terminal and launch **Run-Shine.command in that same updated installation**. It uses the existing sending mode. A draft-only copy stays draft-only. Check Production readiness for any missing Gmail/Notion/self-test configuration before production use.

If your active installation is elsewhere, use **Install-Update.command** and select that existing folder instead. Do not launch the extracted release as a new installation: it contains template settings and no private credentials/history.

## Your configured rules

| Setting | Value |
| --- | --- |
| Daily ceiling | 50 attempted messages across the installation |
| Daily accounting timezone | Existing sender timezone, normally Asia/Bangkok; shared across markets |
| Company sending window | 08:00–11:00, Monday–Friday, in each verified company timezone |
| Minimum interval | 180 seconds, globally between attempts |
| Campaign target | Explicit total chosen in Delivery queue; presets 20 / 30 / 50; custom 1–1000 |
| Renewal | No automatic campaign restart or reset at midnight |
| Follow-ups | Existing enabled/disabled setting preserved; if enabled, each attempt also counts toward both limits |

The ceiling is not a required volume. Target 20 stops that campaign after 20 attempted messages even though the daily maximum is 50. Target 100 can span multiple eligible sending days. Changing the target does not erase prior attempts. Unknown outcomes reserve a slot and block further sending until reconciled.

Three-minute spacing can accommodate 50 messages in a three-hour window if sources, approvals and the worker are ready early enough. Network time, preflight checks, account restrictions or late starts can reduce the actual number. Remaining work waits for a later permitted window; 50 is not a delivery guarantee.

The limit uses the company's verified IANA timezone, including daylight-saving changes. Country alone is insufficient for places such as the US. Missing timezone evidence remains held.

## Exact closing

```text
Thank you,
Shine
Whatsapp: (+0) 000-000-0000
```

The profile now contains `email_signature`. AI prompts request it, and deterministic draft processing applies it once, replacing an old trailing Shine closing. Portfolio inclusion and evidence checks remain mandatory. Existing messages are not sent merely because this signature was added.

For cold outreach, the existing opt-out and postal-address information is preserved before this closing. The exact closing remains the end of the outgoing body. Existing queued drafts whose approval hash no longer matches are held for repair/review rather than silently substituted. Already sent messages are never changed.

## Campaign operation

- A campaign controls delivery volume; it does not discover companies by itself. Use Discovery for your audience and research batches.
- New approved emails queued by the worker are assigned to the active campaign. All ordinary qualification and permission gates remain.
- Queued messages can exceed the remaining campaign allowance. They are held when the target is reached. Increase the same campaign target deliberately if you want more messages from that queue.
- Updating a target preserves the campaign identity, history and spent slots. You cannot reduce it below attempts already reserved.
- Closing a campaign requires selecting the cancellation checkbox. Unattempted queued/blocked entries belonging to it become cancelled. Sent history and duplicate protection remain. A campaign with an uncertain outcome cannot be closed until reconciliation.
- Starting a new campaign is a separate deliberate action. It never clears daily totals, suppressions, Gmail prior-contact checks or previous campaign attempts.
- Old unassigned queue entries are not silently enrolled into a new campaign. They remain held. If you need to migrate those entries, request a review of that specific queue before changing them.
- Pause agent still stops new work. Keep the Mac awake and Run-Shine open for scheduled operation.

## Approval and installation behavior

The first installation applies exactly the requested ceiling, schedule, spacing and signature. Other settings and the sending mode remain unchanged. There is no campaign created automatically.

An already valid, live-tested sending-policy approval can be carried forward specifically for this owner-requested change. An absent, stale or untested approval is not created or renewed. The updater records its decision in `state/migrations/v0.13-policy.json`. Choosing campaign targets is ordinary operation within the approved policy, so it does not require approving a new policy hash for every target.

The migration runs once. Reinstalling the same update does not repeatedly reset later user settings or campaign progress. The updater never rewrites or resets the SQLite database. Campaign tables and the optional outbox column are added when the updated app runs.

## Cost and capacity

There is no fee for choosing a 50/day ceiling or for setting a campaign target. Existing research costs depend on actual API calls. This update does not change the 10-candidate automatic research pilot or its AI/search allowances. No emails or paid research requests were made while building/testing the update.

## Verification and recovery

220 offline tests pass, including full mocked sends up to the 50/day ceiling, campaign completion across days, uncertain outcomes, simultaneous claim attempts, target changes, timezone boundaries, signature and footer preservation, dashboard HTTP actions, and installer credential/history preservation. JavaScript syntax checking passes. Live sending has not been tested with these new settings.

Changed source, profile/sending configuration and any prior approval are backed up under `update-backups/<timestamp>` in the updated installation. To roll back, stop all workers and restore the corresponding backed-up code/config/approval files. Retain the newest SQLite database, credentials and sending history. Request help before replaying any uncertain delivery. If applying this policy migration again after a rollback, its migration marker also needs review; do not delete the sending database.
