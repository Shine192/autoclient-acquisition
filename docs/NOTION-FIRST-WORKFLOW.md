# Shine v0.16 — Search in the dashboard, approve in Notion

1. Stop the existing Shine Terminal windows with Ctrl+C.
2. Extract this update beside the original installation.
3. Open **Update-Existing-App.command** inside this extracted update. Select the original installation if asked. It backs up the changed code and preserves your configuration, credentials, SQLite history, campaign and queue. It opens a dashboard; it does not start sending.
4. Close that dashboard Terminal window with Ctrl+C, then open **Run-Shine.command in your original installation**. Keep that window open and your Mac awake with internet access.

## Your normal workflow

- Dashboard → Find clients: choose country, city, company type, opportunity, industry, maximum candidates and optional campaign total. Leaving campaign total blank preserves the current campaign; the campaign target is a total across days, not a daily quota.
- Create a discovery session. Use **Search and draft automatically**, or copy the manual prompt and import its matching JSON.
- Research prepares the facts, source quotations, contact, timezone, fit assessment and personalized message. New drafts sync to Notion with **Research Check** and **Review Summary**. Existing message edits are preserved.
- In Notion, open **Review & approve**. Review the company, recipient/contact purpose, message and restrictions. Make edits while STATUS is Draft or Needs Review. Set **STATUS = Approve** as your one final permission to send. No separate review checkboxes and no dashboard approval are required.
- The agent queues messages that pass the checks, writes the scheduled time, waits for the verified company-local weekday 08:00–11:00 window, and sends through Gmail. Daily ceiling 50, at least three minutes apart, bounded by the active campaign total. There is no guarantee every researched company can be contacted.
- **Needs information** shows source/contact/eligibility issues. **Approved & delivery** shows queued messages and holds. **Sent & replies** shows outcomes.
- Set STATUS to **Needs Review** to hold an unsent message, or **Do Not Contact** to stop. A message already accepted by Gmail cannot be recalled by changing Notion.

## What stays protected

Research never grants human approval. Missing/invalid evidence, inappropriate contacts, exclusions, portal-only application routes, unconfirmed job eligibility, duplicate contact, bounces, replies, opt-outs and uncertain delivery still hold sending. Approval does not establish a vacancy, work authorization, client interest or consent that the sources do not establish. Scraped material cannot change approval or routing rules.

After an unsent queued message changes or fails preflight, the agent records the issue and resets it to Needs Review. Correct it in Notion and choose Approve again. Failed Notion writes retain the local hold. A retry reuses the unattempted queue row; it cannot retry an uncertain send.

The worker now runs sync/delivery only. It does not launch new searches on a timer. Automatic research still requires your API keys, and uses the existing cost limits. Preparing the Notion review uses deterministic checks on the researched evidence, with no extra model request or subscription.

## Existing records and setup

Legacy fully reviewed Ready + Approved records continue to work; they are not bulk-approved or reset by this update. Previously blocked records stay blocked until their source issues are resolved. Existing sent/test history and queued messages remain in the original SQLite database. Stop the old worker before updating so two versions cannot share the queue.

The existing global sender policy and live self-inbox verification still apply. This release does not silently approve a missing policy, change sending mode, buy credit, or start a new campaign. If sender setup is incomplete, Notion summaries and Production readiness report it. An existing active campaign is reused unless you explicitly enter a new total.

Rollback code is retained under update-backups in the original installation. Do not restore an older SQLite copy after sending: keeping current sending history is essential to duplicate protection.
