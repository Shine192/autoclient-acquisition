# Daily workspace — v0.11.0

Use Run-Shine.command in the installed app to open the dashboard and configured scheduled worker. Existing policy and mode determine whether it can send. Keep that Terminal open; stop it with Ctrl+C. Use Start-Agent.command option 10 if you want only the review panel.

Discovery still uses manual ChatGPT handoff: select an audience, create/copy the prompt, research with web search, then paste/import the matching response. Imported research is untrusted data. Invalid drafts are withheld while eligible company research is preserved.

Open a company review to see a single summary of recipient, sources, fit, timezone and delivery window. One explicit Approve & schedule action records your review in the existing Notion fields and sets Ready. Source/fit/contact problems stay listed together; sender setup is shown separately. The app never treats a published email as automatic consent for a pitch.

A saved edited draft syncs automatically when Notion is connected; failed sync leaves the local draft intact and blocked from approval until synced. Reopen the review after editing. Approval rejects stale records, contacted/closed/suppressed leads and prior attempted/uncertain deliveries. No immediate email-send or global-auto-enable endpoint is added.

Notion review edits are refreshed when you open a company. Credentials are never returned to the browser. The loopback session uses a private cookie and CSRF/origin/host checks. Preview-UI.html uses sample data only and cannot approve or send real outreach.

Gmail/Notion connection presence is not a guarantee of healthy network access. The sender checks its policy and Gmail inbox before eligible sends. Current readiness is authoritative; historical setup notes may describe resolved connection problems.
