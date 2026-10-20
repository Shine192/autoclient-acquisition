# Daily operation — v0.6.0

## Current verified state

Shine's existing local installation connected Gmail, synced Notion, sent one message to Shine's own inbox and verified the reply. Both Orchard and LION drafts are saved in Notion and unapproved. Manual chat drafting was selected: discovery and record keeping can run unattended while the Mac is awake, but new personalized drafts require pasting prompts into ChatGPT/Claude and importing the JSON. No AI API charges are added. Production outreach has not been enabled or live-tested.

## Update without losing setup

1. Stop your panel and workers with Ctrl+C.
2. Extract this ZIP and open `Install-Update.command` in the extracted release.
3. Enter the full existing installation path, without added quotation marks. For Shine it is `~/Downloads/autoclient-acquisition/New/shine-acquisition-agent`.
4. The installer backs up changed code/docs and discovery configuration, preserves existing `.env`, profile, preferences, exclusions, sending settings and all state, and refuses to update while a panel/worker is active. It migrates only the failed `https://remotive.com/feed` URL to the official design/marketing category feeds. It does not enable sending.
5. In your existing installation run `python3 -m acquisition_agent readiness --live` and reopen the panel. Existing Gmail authorization and self-test evidence should remain present.

The CLI alternative, run from the extracted release, is:

```sh
python3 -m acquisition_agent.updater "$PWD" "~/Downloads/autoclient-acquisition/New/shine-acquisition-agent"
```

Do not run a fresh empty installation and expect it to contain the connected installation's credentials. Updates preserve them in their original folder; ZIPs never contain them.

## Start daily work

From the existing project folder:

```sh
python3 -m acquisition_agent agent
```

The combined worker attempts discovery every six hours, uses manual AI, syncs to Notion at most every five minutes, and checks approved delivery every thirty seconds. It records discovery attempts before requests so restarts do not cause a rapid retry loop. Failed attempts remain in `state/agent-events.jsonl`; there is no paid search retry. Run `agent --once` for one cycle. The next discovery attempt is still subject to the six-hour interval.

In another Terminal window:

```sh
python3 -m acquisition_agent dashboard --port 8766
```

Use its full private URL. Review drafts and edit preferences while the combined worker is running. The worker owns the discovery lock, so manual panel discovery/sync tasks require stopping it first; the pipeline, draft editor, readiness view and pause switch remain available.

The worker never sends in draft-only or test mode. Automatic mode also requires the exact policy approval and all per-record gates. Pause prevents new operations after any already-started network request finishes. Keep the Mac awake and Terminal open. No login item, hosted deployment, Telegram service or background OS schedule is installed. Ctrl+C stops cleanly; existing records and queue remain.

## Review and approval

Run `python3 -m acquisition_agent readiness --live` for connection checks and the first blocking reason for each opportunity. The panel also shows configuration blockers without making provider requests. A key/token file is not proof of a healthy connection.

Only mark a record Ready/Approved after verifying current source evidence, recipient purpose, overseas eligibility, actual route, service fit, scope and all email claims. Portal jobs remain manual. Cold prospects do not become vacancies. The current fit threshold is 75; the present examples remain held rather than weakening that threshold to fill a quota.

A proposed exact production manifest is included in `examples/proposed-production-policy.json`. It uses the existing sender, targeting and limits, sets the proposed mode to automatic, keeps row approval enabled, disables follow-ups and all free-work offers, and still has an empty business mailing address. Its adjacent JSON hash is for review, not authorization. Supply your real business mailing address locally before enabling cold outreach; any change requires regenerating and reviewing the hash.

After installation, the live readiness check and owner approval, use the existing SENDING.md process to generate the actual installation's `sending-plan.json` and approve its exact hash. Never copy approval evidence from another installation. No message is sent by exporting a plan or approving it. A newly approved policy permits matching, reviewed records to be queued by the delivery worker without asking for another chat confirmation each time. Substantive replies and contracts always need Shine.

## TLS source error

The current system Python reports LibreSSL 2.8.3 and no TLS 1.3. This is a likely cause of the 23 Digital protocol-version error, not proof of the site's TLS configuration. Install a current stable macOS universal2 Python from https://www.python.org/downloads/macos/ and follow its supplied certificate setup instructions. Open a fresh Terminal and check:

```sh
python3 -c 'import sys, ssl; print(sys.executable); print(ssl.OPENSSL_VERSION); print("TLS 1.3:", ssl.HAS_TLSv1_3)'
```

Then rerun `doctor` and `discover --kind both`. Do not replace Apple's system Python or disable certificate validation. The same agent code still supports Python 3.9, but some public sources may require a newer TLS library. The modern runtime has not been installed or tested by this release.

## Delivery recovery

The outbox now stores both its stable submitted Message-ID and Gmail's actual provider-assigned Message-ID. A failed post-send metadata read does not discard a successful send receipt. Follow-ups cannot queue until the actual sent-message reference is verified. Follow-ups remain off by default.

If send outcome is uncertain, all new sending remains held. First run `reconcile`, which searches Sent by the original stable Message-ID. Gmail may have changed that ID; no search result is never interpreted as proof of non-delivery.

For an explicitly identified Sent message, `reconcile-message OUTBOX_ID GMAIL_MESSAGE_ID` verifies the immutable Gmail ID, SENT label, exact sender, sole recipient, subject, plain-text body and ten-minute attempt window before linking the receipt. It sends nothing. A mismatch stays held for manual investigation; never clear uncertain records to trigger a resend.

## Rollback

Stop panel and workers. The installer prints the `update-backups/TIMESTAMP` folder. Restore its code/docs and `config/discovery.json` to the same relative paths. Gmail credentials, `.env`, profile/preferences/sending configuration and runtime state were not copied or replaced. The added outbox column is compatible with older code. Do not replace the current runtime database with an old copy after real sends; doing so can lose duplicate-prevention history.
