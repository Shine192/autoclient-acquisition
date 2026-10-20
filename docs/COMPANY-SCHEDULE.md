# Company-local sending windows

Version 0.6.1 supports `schedule_basis: "company"`, `send_hours: [9,11]`, and weekdays Monday–Friday. The end is exclusive: sending stops at 11:00 AM. Initial applications and enabled follow-ups use the same window. Test mail to your own inbox bypasses production windows.

For each Notion record, set **Company Time Zone** to an IANA region/city identifier, record an official location page in **Company Time Zone Source**, and check **Company Time Zone Verified** after reviewing the location. Missing or invalid information holds sending. No country-wide US timezone is guessed. For companies with several offices, choose the relevant hiring team's office for advertised jobs or the contacted office for outreach; hold if unclear.

Examples: New York `America/New_York`; Los Angeles `America/Los_Angeles`; London `Europe/London`; Berlin `Europe/Berlin`; Sydney `Australia/Sydney`; Auckland `Pacific/Auckland`. These are examples, not automatic mappings of companies. Daylight saving follows the installed system timezone database.

The sender timezone remains `Asia/Bangkok` for the single daily limit across all destinations: 10 total emails per Bangkok calendar day, not 10 per company or country. The minimum interval remains five minutes. Out-of-window queued items are skipped so other destinations can send in their own window. The worker must be running, the Mac awake and connected. A missed window waits for the next permitted weekday; it does not send outside the window to catch up.

Stop running workers and the panel, then double-click **Apply-Schedule-Update.command** from this separately extracted release. It updates the existing Downloads installation, backs up changed code and sending settings, preserves credentials and records, applies the requested window, and keeps draft-only enabled. It adds the three Notion fields and runs readiness. It does not approve a production policy or send mail.

Changing schedule settings invalidates any earlier policy approval. Review the final policy before enabling automatic mode. Personalization remains manual chat drafting unless an API model is separately configured.

Version 0.6.2: Company Time Zone is a single-select dropdown with 48 IANA timezone options. The agent reads the selected option, including custom valid IANA options you add later. Source and Verified remain separate fields. The older Time Zone field is not used for sending.
