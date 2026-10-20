"""Run from the project folder: python3 -m acquisition_agent --help."""
import argparse
import fcntl
import json
import os
import sys
import time
import uuid
from pathlib import Path
from .core import Store, assess, draft_prompt, now, prepare_lead, read_json, validate_draft, clear_draft_repair, write_json
from .discovery import discover, infer_country, research, source_config
from .providers import Notion, generate
from . import __version__
from . import delivery
from .gmail import Gmail, authorize

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def settings():
    return source_config(read_json(ROOT / "config/preferences.json"), ROOT), read_json(ROOT / "config/profile.json"), read_json(ROOT / "config/exclusions.json")


def check_exclusions(store, config, exclusions):
    for lead in store.leads():
        assessment = assess(lead, config, exclusions)
        if assessment["status"] == "Do Not Contact":
            lead.update(assessment)
            lead["suppression_dirty"] = True
            store.save(lead)
        elif assessment["status"] == "Closed" and lead.get("status") in ("Needs Review", "Discovered", "Draft", "Ready", "Scheduled"):
            lead.update(assessment)
            lead["closure_dirty"] = True
            lead["draft_dirty"] = False
            store.save(lead)
        if lead.get("status") in ("Closed", "Do Not Contact") and lead.get("prompt_file"):
            original = store.root / "prompts" / (lead["id"] + ".txt")
            if original.exists():
                archived = store.root / "prompts-archived" / original.name
                archived.parent.mkdir(parents=True, exist_ok=True)
                original.replace(archived)
                lead["prompt_file"] = str(archived)
                store.save(lead)


def ingest(store, items, config, profile, exclusions, provider, limit, keep_running=lambda: True):
    stats = {"new": 0, "duplicates": 0, "drafts": 0, "prompts": 0, "errors": []}
    api_calls = 0
    for item in items[:limit]:
        if store.paused() or not keep_running():
            stats["paused"] = True
            break
        try:
            lead = prepare_lead(item)
            lead.update(assess(lead, config, exclusions))
            if not store.add(lead):
                stats["duplicates"] += 1
                continue
            stats["new"] += 1
            if lead["status"] in ("Closed", "Do Not Contact"):
                continue
            if not lead.get("company") or len(lead.get("source_text", "").strip()) < 40:
                # Keep an incomplete discovery record, but do not draft a generic email.
                continue
            prompt = draft_prompt(lead, profile, config)
            target = store.root / "prompts" / (lead["id"] + ".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(prompt)
            lead["prompt_file"] = str(target)
            stats["prompts"] += 1
            store.save(lead)
            if provider != "manual":
                if api_calls >= config["max_ai_calls_per_session"]:
                    continue
                api_calls += 1  # failed calls count too; there are no automatic retries
                draft = validate_draft(generate(prompt, provider), lead, profile)
                lead["draft"], lead["draft_dirty"], lead["status"] = draft, True, "Draft"
                store.save(lead)
                stats["drafts"] += 1
        except Exception as exc:
            stats["errors"].append({"source": item.get("url", ""), "error": str(exc)[:200]})
    return stats


def sync(store, notion, source, include_demo=False):
    result = {"synced": 0, "errors": []}
    prefs,profile,exclusions=settings()
    schema_ready=False
    for lead in store.leads():
        if lead.get("is_demo") and not include_demo:
            continue
        try:
            if lead.get("closure_dirty"):
                page = notion.request("pages/" + lead["notion_page_id"], "GET") if lead.get("notion_page_id") else notion.find_lead(source, lead["id"])
                if page:
                    remote_status = (page["properties"].get("STATUS", {}).get("status") or {}).get("name", "Needs Review")
                    if remote_status in ("Needs Review", "Discovered", "Draft", "Ready", "Scheduled", "Closed"):
                        from .providers import research_notes, rich
                        notion.request("pages/" + page["id"], "PATCH", {"properties": {"STATUS": {"status": {"name": "Closed"}}, "Approved": {"checkbox": False}, "Research Notes": {"rich_text": rich(research_notes(lead))}}})
                    lead["notion_page_id"] = page["id"]
                lead["closure_dirty"] = False
            if lead.get("suppression_dirty") and lead.get("notion_page_id"):
                notion.request("pages/" + lead["notion_page_id"], "PATCH", {"properties": {"STATUS": {"status": {"name": "Do Not Contact"}}, "Do Not Contact": {"checkbox": True}, "Approved": {"checkbox": False}}})
                lead["suppression_dirty"] = False
                lead["draft_dirty"] = False
            notion.save_lead(source, lead)
            store.save(lead)
            if lead.get('status') not in delivery.STOP | {'Sent','Sending'}:
                if not schema_ready:
                    delivery.setup_schema(notion,source);schema_ready=True
                from .notion_review import prepare
                prepare(store,notion,lead,read_json(ROOT/'config/sending.json'),profile,prefs,exclusions)
            result["synced"] += 1
        except Exception as exc:
            result["errors"].append({"id": lead["id"], "error": str(exc)[:200]})
    return result


def run_discovery(store, config, profile, exclusions, args):
    if store.paused():
        raise ValueError("Agent is paused. Use resume when ready")
    row = store.db.execute("SELECT value FROM flags WHERE name='search_offset'").fetchone()
    local_config = dict(config, _exclusions=exclusions, search_query_offset=int(row[0]) if row else 0)
    keep_running = getattr(args, "keep_running", lambda: not store.paused())
    items, errors = discover(local_config, args.search, args.kind, getattr(args, "query", None), keep_running)
    if args.search and not getattr(args, "query", None):
        store.db.execute("INSERT OR REPLACE INTO flags VALUES ('search_offset',?)", (str(local_config["search_query_offset"] + config["max_search_calls_per_session"]),))
        store.db.commit()
    result = ingest(store, items, config, profile, exclusions, args.ai, args.limit, keep_running)
    if not keep_running():
        result["paused"] = True
    result["errors"] = errors + result["errors"]
    result['sources'] = {'rss_feeds':len(config.get('rss_feeds',[])) if args.kind!='cold' else 0,
                         'watchlist':sum(1 for e in config.get('watchlist',[]) if e.get('enabled',True) and (args.kind=='both' or (args.kind=='jobs')==(e['kind']=='Posted Job'))),
                         'researched_candidates':len(items), 'paid_search_enabled':args.search}
    return result


def starter(store, config, profile, exclusions):
    items = read_json(ROOT / "examples/researched-prospects.json")
    result = ingest(store, items, config, profile, exclusions, "manual", 20)
    result["review_drafts_loaded"] = 0
    for draft in read_json(ROOT / "examples/starter-drafts.json"):
        lead = store.get(draft["lead_id"])
        if lead.get("draft") or lead.get("status") in ("Closed", "Do Not Contact", "Sent", "Sending", "Replied", "Interview", "Won"):
            continue
        lead["draft"] = validate_draft(draft, lead, profile)
        lead["draft_dirty"], lead["status"] = True, "Draft"
        lead["starter_seed"] = True
        store.save(lead)
        result["review_drafts_loaded"] += 1
        result["drafts"] += 1
    return result


def worker(store, config, profile, exclusions, args):
    # One worker per local state directory. No remote/global lock across multiple Macs.
    lock = (store.root / "worker.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError("Another local worker already owns this state directory") from None
    notion = Notion()
    source = config.get("notion_sessions_source_id")
    if not source:
        raise ValueError("Set notion_sessions_source_id in preferences.json")
    print("Worker v" + __version__ + " active. Manual AI mode=" + str(args.ai == "manual") + ". Ctrl+C to stop. Discovery only. Use delivery-worker separately for configured sending.", flush=True)
    while True:
        try:
            if not store.paused():
                # Reload exclusions/preferences so editing these takes effect next session.
                config, profile, exclusions = settings()
                check_exclusions(store, config, exclusions)
                for page in notion.query(source, {"property": "STATUS", "status": {"equals": "Queued"}}):
                    if store.paused():
                        break
                    session_id = page["id"]
                    props = page.get("properties", {})
                    requested = props.get("Result Limit", {}).get("number") or 20
                    args.limit = max(1, min(int(requested), 20))
                    session_run = str(uuid.uuid4())
                    store.session(session_id, "Running", {"run_id": session_run, "started": now()})
                    notion.session_update(session_id, "Running", "Research running; no emails will be sent. Run " + session_run)
                    def still_running():
                        if store.paused():
                            return False
                        current = notion.request("pages/" + session_id, "GET")
                        return current["properties"]["STATUS"]["status"]["name"] == "Running"
                    args.keep_running = still_running
                    try:
                        result = run_discovery(store, config, profile, exclusions, args)
                        result["notion_sync"] = sync(store, notion, config["notion_leads_source_id"])
                        has_errors = bool(result["errors"] or result["notion_sync"]["errors"])
                        status = "Paused" if result.get("paused") else "Failed" if has_errors else "Completed"
                        store.session(session_id, status, result)
                        notion.session_update(session_id, status, json.dumps(result)[:8000], result["new"])
                        print(json.dumps({"session": session_id, "status": status, **result}), flush=True)
                    except Exception as exc:
                        store.session(session_id, "Failed", {"error": str(exc)[:200]})
                        notion.session_update(session_id, "Failed", str(exc)[:200])
            if args.once:
                return
            time.sleep(30)
        except KeyboardInterrupt:
            print("Worker stopped. Queued sessions stay in Notion.")
            return
        except Exception as exc:
            print("Worker error: " + str(exc)[:200], file=sys.stderr, flush=True)
            if args.once:
                raise
            time.sleep(30)



def sending_command(args, store, prefs, profile, exclusions):
    sending = read_json(ROOT / "config/sending.json")
    delivery.validate_config(sending, profile)
    token = store.root / "credentials/gmail-token.json"
    gmail = Gmail(token)
    name = args.command
    if name == "sending-plan":
        manifest = delivery.policy(sending, profile, prefs, exclusions)
        result = {"sha256": delivery.fingerprint(manifest), "policy": manifest}
        write_json(store.root / "sending-plan.json", result)
        print(json.dumps(result, indent=2))
    elif name == "approve-sending":
        manifest = delivery.policy(sending, profile, prefs, exclusions)
        expected = delivery.fingerprint(manifest)
        if sending['mode'] != 'automatic' or args.sha256 != expected:
            raise ValueError("Set desired mode automatic, run sending-plan, then approve that exact hash")
        evidence = store.root / 'test-evidence.json'
        if not evidence.exists() or not read_json(evidence).get('reply_verified'):
            raise ValueError("Complete live self-inbox send and reply verification first")
        write_json(store.root / 'sending-approval.json', {'sha256': expected, 'approved_at': now(), 'sender': profile['sender_email']})
        print("Exact sending policy approved. No message sent by this command.")
    elif name == "gmail-auth":
        print("Authorized " + authorize(args.client_file, token, profile['sender_email'], args.manual_browser))
    elif name == "gmail-check":
        identity = gmail.identity()
        if identity != profile['sender_email'].lower():
            raise ValueError('Gmail sender mismatch')
        print(json.dumps({'sender': identity, 'authorized': True}))
    elif name == "notion-schema":
        print(json.dumps(delivery.setup_schema(Notion(), prefs['notion_leads_source_id']), indent=2))
    elif name == "queue":
        with delivery.lock(store):
            lead = delivery.remote_lead(store, Notion(), store.get(args.lead_id))
            print(json.dumps(delivery.queue(store, lead, sending, profile, prefs, exclusions), indent=2))
    elif name == "outbox":
        print(json.dumps([{k: r[k] for k in ('id', 'lead_id', 'stage', 'mode', 'state', 'recipient', 'error', 'due_at', 'sent_at')} for r in delivery.rows(store)], indent=2))
    elif name == "suppress":
        with delivery.lock(store):
            delivery.suppress(store, args.value, args.reason)
        print('Suppression recorded')
    elif name == "verify-test-reply":
        evidence = read_json(store.root / 'test-evidence.json')
        item = next(i for i in delivery.rows(store) if i['id'] == evidence['outbox_id'])
        from .verification import test_reply_found
        found = test_reply_found(gmail.thread(item['thread_id']), item, profile['sender_email'])
        if not found:
            raise ValueError('Reply to the AGENT TEST message in Gmail, then run this command again')
        evidence['reply_verified'] = True
        evidence['verified_at'] = now()
        write_json(store.root / 'test-evidence.json', evidence)
        print('Live self-inbox delivery and reply verified. Production remains gated by policy approval.')
    elif name == 'reconcile-message':
        print(json.dumps(delivery.reconcile_receipt(store,gmail,args.outbox_id,args.gmail_id,profile['sender_email']),indent=2))
    elif name == "reconcile":
        print(json.dumps(delivery.reconcile(store, gmail), indent=2))
    elif name == "poll-replies":
        with delivery.lock(store):
            print(json.dumps(delivery.poll(store, gmail, sending), indent=2))
        print(json.dumps(delivery.sync_delivery(store, Notion()), indent=2))
    else:
        while True:
            # Reload on every tick; config changes invalidate approval.
            prefs, profile, exclusions = settings()
            sending = read_json(ROOT / 'config/sending.json')
            if sending['mode'] == 'draft-only':
                print(json.dumps({'state':'draft-only', 'message':'No sending or reply scanning in this mode.'}), flush=True)
                return
            notion = Notion()
            try:
                if sending['mode'] == 'automatic' and not store.paused():
                    with delivery.lock(store):
                        delivery.queue_ready(store, notion, sending, profile, prefs, exclusions)
                        delivery.followups(store, gmail, notion, sending, profile, prefs, exclusions)
                result = delivery.tick(store, gmail, notion, sending, profile, prefs, exclusions, research)
                result['notion_sync'] = delivery.sync_delivery(store, notion)
                print(json.dumps(result), flush=True)
            except (ValueError, OSError, KeyError) as exc:
                if name == 'send-once':
                    raise
                print('Delivery held: ' + str(exc)[:200], flush=True)
            if name == 'send-once':
                break
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                print('Delivery worker stopped; queue preserved.')
                break


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Shine's discovery, Notion review and controlled Gmail agent.")
    parser.add_argument("--state-dir", default=str(ROOT / "state"))
    commands = parser.add_subparsers(dest="command", required=True)
    panel = commands.add_parser("dashboard", help="Open a private local control panel; no sending controls")
    panel.add_argument("--port", type=int, default=8765)
    commands.add_parser("doctor", help="Check configuration without making requests")
    ready=commands.add_parser("readiness", help="Explain setup and opportunity holds; never sends")
    ready.add_argument('--live',action='store_true',help='Also check Gmail identity and read current Notion reviews')
    agent=commands.add_parser('agent',help='Run combined local discovery, sync and approved delivery while Mac is awake')
    agent.add_argument('--interval-hours',type=int,default=6)
    agent.add_argument('--once',action='store_true')
    commands.add_parser("status")
    commands.add_parser("pause")
    commands.add_parser("resume")
    commands.add_parser("sending-plan", help="Export exact policy and approval hash; does not enable sending")
    approve = commands.add_parser("approve-sending", help="Record owner's approval of an exact policy hash after live test")
    approve.add_argument("sha256")
    auth = commands.add_parser("gmail-auth", help="Authorize local Gmail desktop app in your browser")
    auth.add_argument("client_file")
    auth.add_argument("--manual-browser", action="store_true", help="Prepare a private authorization URL without launching the browser")
    commands.add_parser("gmail-check")
    commands.add_parser("notion-schema", help="Add missing delivery review fields without replacing existing fields")
    enqueue = commands.add_parser("queue", help="Read Notion review and queue one lead; test mode routes to self")
    enqueue.add_argument("lead_id")
    commands.add_parser("outbox")
    commands.add_parser("send-once", help="Deliver at most one eligible queued message")
    commands.add_parser("delivery-worker", help="Poll replies and send queue while Mac is awake; Ctrl+C stops")
    commands.add_parser("poll-replies")
    receipt=commands.add_parser('reconcile-message',help='Link an uncertain send to an exact existing Sent receipt; never sends')
    receipt.add_argument('outbox_id');receipt.add_argument('gmail_id')
    commands.add_parser("reconcile", help="Search Sent by stable Message-ID; never retries uncertain delivery")
    commands.add_parser("verify-test-reply", help="Verify a live reply in your self-test thread")
    suppression = commands.add_parser("suppress")
    suppression.add_argument("value")
    suppression.add_argument("--reason", default="Owner requested suppression")
    commands.add_parser("demo", help="Offline sample; never sends or syncs")
    seed = commands.add_parser("starter", help="Import three source-researched agency prospects and review drafts; never sends")
    seed.add_argument("--sync", action="store_true", help="Also sync to your Notion review database")
    imp = commands.add_parser("import-leads", help="Import researched source text from JSON")
    imp.add_argument("file")
    imp.add_argument("--limit", type=int, default=20)
    imp.add_argument("--ai", choices=["manual", "openai", "anthropic"], default="manual")
    url = commands.add_parser("research-url", help="Research a supplied public page")
    url.add_argument("url")
    url.add_argument("--company", default="")
    url.add_argument("--kind", choices=["Posted Job", "Cold Outreach"], default="Posted Job")
    url.add_argument("--title", default="Email design opportunity")
    url.add_argument("--ai", choices=["manual", "openai", "anthropic"], default="manual")
    draft = commands.add_parser("import-draft", help="Import JSON returned by ChatGPT or Claude")
    draft.add_argument("file")
    retry = commands.add_parser("generate-draft", help="Generate or retry one draft using an API")
    retry.add_argument("lead_id")
    retry.add_argument("--ai", choices=["openai", "anthropic"], required=True)
    export = commands.add_parser("export", help="Export all local leads and drafts")
    export.add_argument("file")
    sn = commands.add_parser("sync-notion")
    sn.add_argument("--include-demo", action="store_true")
    for name in ("discover", "worker"):
        p = commands.add_parser(name)
        p.add_argument("--ai", choices=["manual", "openai", "anthropic"], default="manual")
        p.add_argument("--search", action="store_true", help="Enable billed Firecrawl search calls")
        p.add_argument("--kind", choices=["both", "jobs", "cold"], default="both")
        p.add_argument("--limit", type=int, default=20)
        if name == "worker":
            p.add_argument("--once", action="store_true")
        else:
            p.add_argument("--query", help="Override paid search query (posted jobs only)")
    args = parser.parse_args()
    config, profile, exclusions = settings()
    store = Store(args.state_dir)
    if hasattr(args, "limit") and not 1 <= args.limit <= 20:
        parser.error("limit must be 1–20")
    try:
        check_exclusions(store, config, exclusions)
        if args.command == "dashboard":
            from .panel import serve
            if not 0<=args.port<=65535:
                raise ValueError("Port must be 0–65535")
            serve(ROOT, store.root, args.port)
        elif args.command == 'agent':
            from .runner import run
            run(store,ROOT,args.interval_hours,args.once)
        elif args.command == 'readiness':
            from .readiness import report
            config_send=read_json(ROOT/'config/sending.json')
            gmail_live=Gmail(store.root/'credentials/gmail-token.json') if args.live else None
            notion_live=Notion() if args.live and os.getenv('NOTION_TOKEN') else None
            print(json.dumps(report(store,config_send,profile,config,exclusions,gmail_live,notion_live),indent=2))
        elif args.command == "doctor":
            print(json.dumps({"version": __version__, "python": sys.version.split()[0], "tls_library": __import__("ssl").OPENSSL_VERSION, "tls13_available": __import__("ssl").HAS_TLSv1_3, "ai_mode_default": "manual", "paid_ai_ready": bool(os.getenv("AI_MODEL") and (os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))), "search_key_present": bool(os.getenv("FIRECRAWL_API_KEY")), "notion_key_present": bool(os.getenv("NOTION_TOKEN")), "notion_sessions_configured": bool(config.get("notion_sessions_source_id")), "exclusions_confirmed": exclusions["confirmed"], "sender": profile["sender_email"], "gmail_sending": "implemented; requires local OAuth and live self-test", "local_gmail_credentials_present": (store.root / "credentials/gmail-token.json").exists(), "sending_mode": read_json(ROOT / "config/sending.json")["mode"]}, indent=2))
        elif args.command in ("sending-plan", "approve-sending", "gmail-auth", "gmail-check", "notion-schema", "queue", "outbox", "send-once", "delivery-worker", "poll-replies", "reconcile", "reconcile-message", "verify-test-reply", "suppress"):
            sending_command(args, store, config, profile, exclusions)
        elif args.command == "status":
            counts = {}
            for lead in store.leads():
                counts[lead["status"]] = counts.get(lead["status"], 0) + 1
            print(json.dumps({"paused": store.paused(), "leads": counts}, indent=2))
        elif args.command in ("pause", "resume"):
            store.pause(args.command == "pause")
            print("Agent " + ("paused" if store.paused() else "resumed"))
        elif args.command == "demo":
            items = read_json(ROOT / "examples/demo-leads.json")
            result = ingest(store, items, config, profile, exclusions, "manual", 20)
            for lead in store.leads():
                if lead.get("is_demo") and lead.get("prompt_file"):
                    sample = {"lead_id": lead["id"], "subject": "[DEMO] Freelance email design for Sample Studio", "body": "Hi Sample Studio team,\n\nYour sample brief mentions an ongoing freelance email designer for e-commerce clients. I create Figma email designs and build approved layouts in Klaviyo using reusable blocks. I could support campaign layouts and flows while following each client's brand guidelines.\n\nMy Figma design rate is USD 20–30 per email; Klaviyo building is quoted separately. You can see my work here: " + profile["portfolio_url"] + "\n\nWould it be useful to discuss a small paid design trial?\n\nShine\n\n[DEMO: fictional company; do not send]", "evidence": [{"url": lead["url"], "quote": "ongoing freelance email designer for e-commerce clients"}]}
                    lead["draft"] = validate_draft(sample, lead)
                    lead["status"] = "Draft"
                    lead["draft_dirty"] = True
                    store.save(lead)
            print(json.dumps(result, indent=2))
        elif args.command == "import-leads":
            print(json.dumps(ingest(store, read_json(args.file), config, profile, exclusions, args.ai, args.limit), indent=2))
        elif args.command == "starter":
            if store.paused():
                raise ValueError("Agent is paused; resume before importing starter prospects")
            result = starter(store, config, profile, exclusions)
            if args.sync:
                result["notion_sync"] = sync(store, Notion(), config["notion_leads_source_id"])
            print(json.dumps(result, indent=2))
            if result["errors"] or result.get("notion_sync", {}).get("errors"):
                return 1
        elif args.command == "research-url":
            text = research(args.url)
            raw = {"url": args.url, "title": args.title, "company": args.company, "kind": args.kind, "country": infer_country(text, config), "source_text": text}
            if args.kind == "Cold Outreach":
                raw["website"] = args.url
            print(json.dumps(ingest(store, [raw], config, profile, exclusions, args.ai, 1), indent=2))
        elif args.command == "import-draft":
            data = read_json(args.file)
            lead = store.get(data.get("lead_id", ""))
            if lead["status"] in ("Do Not Contact", "Closed", "Sent", "Replied", "Won"):
                raise ValueError("Lead is excluded, closed or contacted")
            lead["draft"] = validate_draft(data, lead, profile)
            clear_draft_repair(lead)
            lead.pop("starter_seed", None)
            lead["draft_dirty"], lead["status"] = True, "Draft"
            store.save(lead)
            print("Draft saved. Review all claims and scope before any future sending.")
        elif args.command == "generate-draft":
            if store.paused():
                raise ValueError("Agent is paused")
            lead = store.get(args.lead_id)
            if lead["status"] in ("Do Not Contact", "Closed", "Sent", "Replied", "Won"):
                raise ValueError("Lead is excluded, closed or contacted")
            lead["draft"] = validate_draft(generate(draft_prompt(lead, profile, config), args.ai), lead, profile)
            clear_draft_repair(lead)
            lead.pop("starter_seed", None)
            lead["draft_dirty"], lead["status"] = True, "Draft"
            store.save(lead)
            print("Draft generated; sync to Notion for review")
        elif args.command == "export":
            write_json(args.file, store.leads())
            print("Exported " + str(len(store.leads())) + " leads")
        elif args.command == "sync-notion":
            result = sync(store, Notion(), config["notion_leads_source_id"], args.include_demo)
            print(json.dumps(result, indent=2))
            if result["errors"]:
                return 1
        elif args.command == "discover":
            result = run_discovery(store, config, profile, exclusions, args)
            print(json.dumps(result, indent=2))
            if result["errors"]:
                return 1
        elif args.command == "worker":
            worker(store, config, profile, exclusions, args)
    except KeyboardInterrupt:
        print("Stopped; no email sent.", file=sys.stderr)
        return 130
    except (ValueError, OSError, KeyError) as exc:
        print("Error: " + str(exc)[:300], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
