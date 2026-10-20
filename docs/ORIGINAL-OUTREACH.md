# Connect your original Outreach Management System

This update keeps your current Mac installation, credentials, SQLite history,
queues, campaigns and existing Notion links. The cloud version remains saved.
New research can use your original database. Existing contacts are not imported
as new applications, reapproved, overwritten, or automatically contacted.

## Install once

1. In your running Shine Terminal window, press Control+C to stop the dashboard
   and worker. Leave the original project folder where it is.
2. Double-click Install-Shine-v0.17.0.command in this extracted update. It
   already targets your current folder:
   ~/Downloads/autoclient-acquisition/New/shine-acquisition-agent
   Use Install-Update.command only if your existing installation moved.
3. The installer verifies that the Mac's Notion connection can read your
   original database before switching future research there. If it says
   "connection pending", your old connection is unchanged.
4. If access is missing, open the original Outreach Management System in Notion.
   Use the page's three-dot menu → Connections → Add connections, and choose
   the same Shine Job Acquisition Agent integration used by this Mac. Confirm
   the Notion access prompt yourself. This shares that database with the agent;
   it does not grant public access. Do not create or paste a new API key here.
5. Double-click Connect-Outreach.command **inside the original installation**
   if the connection was pending. It verifies access, field types and history;
   success says `"connected": true`. It changes the research destination only.
6. Open Run-Shine.command inside that original installation.

## Each session

Fill the dashboard form → research and draft → open Notion → review the
recipient, source, Research Check, subject and body → set STATUS to Approve.
The running Mac worker queues eligible messages for weekdays 08:00–11:00 in
the verified company timezone, up to your campaign target and maximum 50/day.
Keep the Mac awake and the Shine Terminal running. Follow-ups remain governed
by your current configuration; this update does not enable them or create a
campaign. Old STATUS=Ready is not new approval in this database.

Notion views: All contacts, Review & approve, Approved & scheduled,
Needs information, and Sent & replies. A clean Review & approve view can be
empty until new research has passed its checks. Existing manual contacts remain
in All contacts. Extra review checkboxes are hidden from the main workflow.

Matching an existing website or email holds a new result. The error identifies
the existing Notion page. This protects sent history and manual drafts; resolve
possible duplicates before proceeding. A failed history query stops sending.
Changing a queued email requires a new approval. Unknown delivery is never
blindly retried. Do Not Contact, replies, bounces and opt-outs stop later sends.

## Checks completed / still needed

- Original Notion structure and views updated; 22 existing rows and 12 Sent
  records preserved, with all original property values unchanged.
- Legacy GitHub AutoClient Outreach workflow displayed Disabled on 2026-10-20.
  Leave that workflow disabled while this Mac sender is used.
- Offline tests cover the real field adapter, single Notion approval, timing,
  sent-date updates, edited-message reapproval, unavailable history, legacy
  duplicates, retries, and preserved credentials/queue/settings.
- After the owner enabled access, the Mac token successfully read the original
  database and all 22 records. A live create/read check passed using a recipient-
  free Do Not Contact test record, which was then archived.
  Installation, the first real research sync and an original-database self-inbox
  send still need verification. No production email was sent in this migration.

## Recovery

The installer keeps a timestamped update-backups folder inside your original
installation. It never resets state/agent.sqlite3 or replaces credentials.
The connection step backs up preferences, its connection file and any existing
policy approval separately. To roll back: stop Shine, restore code/config from
that backup, keep the current state directory and credentials, then run
sending-plan to check approval. Never restore an old SQLite history over newer
sends or launch two installations using separate copies of history.

If an error says policy approval is stale, inspect sending-plan and approve
that exact plan through the existing workflow. This update carries only an
already valid, live-tested approval when just the requested database destination
changes. It never authorizes an unapproved or changed sending policy.
