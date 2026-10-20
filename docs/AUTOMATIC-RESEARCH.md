# Shine Mac update — automatic research and drafts

This update removes the need to copy research prompts and JSON between ChatGPT and the agent. It runs on your Mac. Your saved cloud version is unchanged and requires no Cloud billing setup.

## Install into your existing app

1. Stop the current app and its worker Terminal windows with **Ctrl+C**. Keep the existing installation folder.
2. Extract this ZIP. Double-click **Update-Existing-App.command** in the extracted folder. It updates `~/Downloads/autoclient-acquisition/New/shine-acquisition-agent`, backs up changed files, and preserves your settings, Notion connection, Gmail credentials and SQLite sending history. It opens the dashboard only; it does not launch a sending worker.
3. Close that dashboard Terminal after the update. In your **existing installation folder**, double-click **Configure-Automatic-Research.command**. Paste an OpenAI API key and a Firecrawl API key into its hidden Terminal prompts. Never paste keys into chat. Existing other credentials and AI_MODEL settings are retained.
4. In your existing folder, double-click **Run-Shine.command**. It loads the keys and starts the workspace and scheduled worker under your existing sending policy. Keep this Terminal running and your Mac awake.
5. Open **Discovery**, select location, company type and industries, and choose at most **10** candidates. Click **Create discovery session**, then **Search and draft automatically**. Session activity shows progress and saved drafts. Notion sync happens automatically when its configured connection works.

## API accounts and cost

ChatGPT Plus and Claude Pro do not include this agent's API usage. OpenAI API credit is separate; begin with the previously discussed $5 manual prepaid credit and disable auto-reload if you want manual top-ups. Do not buy a Firecrawl subscription for this pilot; use the Free allowance. The setup command does not buy credit, subscribe, or contact providers.

The fixed automatic model is **gpt-6-luna**. Its availability in your account is untested. The initial live request checks access; there is no paid model fallback. Listed standard short-context prices checked 2026-10-19: $0.10/M input tokens, $0.50/M output tokens. Confirm rates on https://developers.openai.com/api/docs/pricing before future use. Firecrawl pricing: https://www.firecrawl.dev/pricing .

Automatic research reserves a conservative allowance before each paid request. Limits across this installation:

- Up to 10 candidate hosts/postings per session; fewer may qualify.
- Up to 3 search queries per session, 10 results each, 2 search credits reserved per request.
- Up to 3 permitted public pages per candidate (30 page attempts). Pages are fetched directly; there is no paid scraping fallback.
- Up to 1 AI request per candidate, 5,000 output tokens, a bounded input; no automatic paid retries.
- **$0.50 reserved AI allowance per session; $2 per UTC calendar month; 50 search credits/month.** These are conservative app limits, not recurring charges or provider billing guarantees. They cover only this automatic feature, not other apps or CLI AI commands. Do not delete or reset `state/agent.sqlite3` to regain allowance.
- Search/page cache lasts 24 hours. Existing companies/jobs are skipped without regenerating drafts. A cached job is still rechecked by the existing dispatch gates before sending.

Session activity reports reserved allowance separately from the token-based cost estimate. Actual provider billing is authoritative. Failed or timed-out requests retain their reservation because they might have been processed. Unknown or unexpectedly high token usage creates a persistent `automatic_billing_hold`; check billing before clearing that flag with technical help.

## Research and sending behavior

The app searches, reads permitted sources, extracts observed company facts and published shared business addresses, validates exact evidence quotes, and saves valid drafts. It cannot discover every company or read every website. Blocked pages, inaccessible originals, directory results, unknown facts and missing addresses are held or skipped. Advertised jobs use the original employer posting; portal-only roles still need the appropriate application route.

AI-supplied source text, recipients and approval fields are discarded. Evidence must match the text the app actually fetched. Generated content can still need editorial review; exact quotes do not prove every sentence of an AI draft. Verify the first pilot's tone, claims, targeting and contact purpose.

This feature does **not** approve new prospects, queue emails, change limits, or alter your company-local 9–11am sending rules. Existing already-approved applications may continue under the existing scheduled worker. New records remain drafts/Needs Review until the existing review and sending gates pass. The combined worker waits while a research/import/sync task owns the shared work lock; this can briefly delay sending.

Use **Pause agent** to stop new requests. An in-flight request may finish; saved data and usage remain. Keep your Mac awake with the app running for research and scheduled delivery. Closing the lid or stopping the app suspends this local workflow.

## Recovery

- Missing key or API credit: configure keys locally, restart the app, then use a session that has not started. No requests run merely because keys are saved.
- A stopped/interrupted session: inspect Session activity first. Do not reimport or repeatedly click. A started automatic session is never replayed; create a new one deliberately. Existing lead IDs and cached sources prevent overwrite and unnecessary repeat work, but a company that failed before saving may incur another request.
- Draft rejected: company research is retained when valid. Its review explains the missing evidence. Manual prompts/JSON import remain collapsed as a fallback.
- Notion failure: drafts stay in SQLite. Use **Sync to Notion** after fixing the connection; no AI redrafting is needed. The updater preserves your database/source IDs.
- Worker busy: wait for its current feed/sync cycle, then retry. Older workers need to be stopped before the update. Use a single Run-Shine instance.
- Rollback: stop the app and all workers. Changed code/config files are in `update-backups/<timestamp>` inside your existing installation. Restore those changed files while retaining the current state database and credentials. Never restore an older sending database over new sends.

## Validation status

194 offline tests pass, including dashboard HTTP integration, full mocked research-to-draft flow, exact-source validation, suppression/exclusions, duplicate protection, concurrent usage reservations, timeouts, pause, Notion failure, worker locking, updater preservation, and the existing delivery/reply tests. JavaScript syntax check passes.

No live API pilot or external email was sent for this update. Your current installation has Notion configured but is missing OpenAI and Firecrawl API keys. Configure those locally, then start with a small 5–10 candidate pilot before expanding.
