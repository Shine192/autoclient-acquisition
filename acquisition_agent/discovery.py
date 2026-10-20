"""RSS, optional paid search, and direct URL research."""
import re
import json
from pathlib import Path
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from .core import relevant, excluded
from .network import fetch_text, plain_text
from .providers import search
from .screening import company_country


def source_config(config, root):
    """Optional additive sources; existing targeting and credentials stay intact."""
    path = Path(root) / 'config/discovery.json'
    if not path.exists():
        return config
    extra = json.loads(path.read_text())
    feeds = extra.get('rss_feeds', [])
    watchlist = extra.get('watchlist', [])
    if not isinstance(feeds, list) or len(feeds)>10 or any(not isinstance(u,str) or not u.startswith('https://') for u in feeds):
        raise ValueError('Discovery RSS list must contain at most 10 HTTPS URLs')
    if not isinstance(watchlist,list) or len(watchlist)>20:
        raise ValueError('Discovery watchlist must contain at most 20 entries')
    for entry in watchlist:
        if not isinstance(entry,dict) or entry.get('kind') not in ('Posted Job','Cold Outreach') or not isinstance(entry.get('url'),str) or not entry['url'].startswith('https://'):
            raise ValueError('Each watchlist entry needs HTTPS url and explicit opportunity kind')
        pages=entry.get('research_urls',[])
        if not isinstance(pages,list) or len(pages)>2 or any(not isinstance(u,str) or not u.startswith('https://') or urlsplit(u).hostname!=urlsplit(entry['url']).hostname for u in pages):
            raise ValueError('Use at most two research URLs on the same company host')
    return dict(config, rss_feeds=list(dict.fromkeys(config.get('rss_feeds',[])+feeds)), watchlist=watchlist)


def research(url):
    parts = urlsplit(url)
    robot_url = parts.scheme + "://" + parts.netloc + "/robots.txt"
    try:
        robots = fetch_text(robot_url)
    except ValueError as exc:
        if str(exc) != "Research HTTP 404":
            raise ValueError("Cannot check research robots rules: " + str(exc)) from None
        robots = ""
    parser = RobotFileParser()
    parser.parse(robots.splitlines())
    if not parser.can_fetch("ShineAcquisitionResearch", url):
        raise ValueError("Source disallows this research fetch")
    return plain_text(fetch_text(url))


def rss(url):
    root = ET.fromstring(fetch_text(url))
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        description = plain_text(item.findtext("description", ""))
        if relevant(title + " " + description):
            company = title.split(":", 1)[0] if ":" in title else ""
            date = item.findtext("pubDate", "")
            try:
                date = parsedate_to_datetime(date).isoformat() if date else ""
            except (ValueError, TypeError):
                date = ""
            yield {"title": title, "url": item.findtext("link", ""), "company": company, "kind": "Posted Job", "source_text": description, "posted_at": date, "research_source_url": url, "research_level": "RSS excerpt"}


def infer_country(text, config):
    return company_country(text, config["countries"])


def queries(config):
    for market in config["search_markets"]:
        yield '("email designer" OR "Klaviyo") (freelance OR contract) remote "' + market + '"', "Posted Job"
        yield '("email marketing agency" OR "Klaviyo agency") "' + market + '"', "Cold Outreach"
        yield '"Klaviyo" ("shop" OR "store" OR "brand") "' + market + '"', "Cold Outreach"


def discover(config, use_search=False, kind="both", query_override=None, keep_running=lambda: True):
    errors, leads = [], []
    for entry in config.get('watchlist', []):
        if entry.get('enabled', True) and (kind=='both' or (kind=='jobs') == (entry['kind']=='Posted Job')):
            leads.append({k:entry[k] for k in ('url','company','title','kind','research_urls') if k in entry})
    if kind != "cold":
        for feed in config["rss_feeds"]:
            if not keep_running():
                return leads, errors
            try:
                leads.extend(rss(feed))
            except Exception as exc:
                errors.append({"source": feed, "error": str(exc)[:200]})
    if use_search:
        selected = [(query_override, "Posted Job")] if query_override else list(queries(config))
        selected = [(q, k) for q, k in selected if kind == "both" or (kind == "jobs") == (k == "Posted Job")]
        if selected and not query_override:
            offset = config.get("search_query_offset", 0) % len(selected)
            selected = selected[offset:] + selected[:offset]
        for query, opportunity_kind in selected[:config["max_search_calls_per_session"]]:
            if not keep_running():
                return [], errors
            try:
                for result in search(query, config["search_results_per_query"]):
                    leads.append({"url": result["url"], "title": result.get("title", "Opportunity"), "kind": opportunity_kind, "source_text": "", "search_snippet": result.get("description", "")})
            except Exception as exc:
                errors.append({"source": "Search", "error": str(exc)[:200]})
    # Fetch full pages rather than treating search snippets as established facts.
    seen, output = set(), []
    for lead in leads:
        if not keep_running():
            break
        if len(output) >= config["max_candidates_per_session"]:
            break
        if lead["url"] in seen:
            continue
        seen.add(lead["url"])
        try:
            if excluded(lead, config.get('_exclusions', {})):
                continue
            full = research(lead["url"])
            primary_text = full
            documents = [{'url':lead['url'],'text':full}]
            for extra_url in lead.pop('research_urls', []):
                if not keep_running():
                    break
                try:
                    extra_text=research(extra_url)
                    documents.append({'url':extra_url,'text':extra_text})
                except Exception as exc:
                    errors.append({'source':extra_url,'error':str(exc)[:200]})
            lead['source_documents']=documents
            lead['checked_at']=datetime.now(timezone.utc).isoformat()
            if lead.get('kind')=='Cold Outreach':
                lead['research_warning']='Prospective client only; no vacancy, budget, freelance interest or Thailand eligibility confirmed.'
            full='\n\n'.join(d['text'] for d in documents)
            lead["source_text"] = primary_text
            lead["research_source_url"] = lead["url"]
            lead["research_level"] = "Full page"
            lead["country"] = infer_country(full, config)
            if relevant(lead.get("title", "") + " " + full):
                if lead["kind"] == "Cold Outreach":
                    lead["website"] = lead["url"]
                output.append(lead)
        except Exception as exc:
            if lead.get("research_level") == "RSS excerpt" and len(lead.get("source_text", "").strip()) >= 40:
                # This text was already published in the successfully fetched feed.
                # Preserve its actual source; do not retry or bypass a blocked page.
                lead["research_warning"] = "Original page unavailable (" + str(exc)[:160] + "); public RSS excerpt only. Verify listing and company details manually."
                lead["country"] = infer_country(lead["source_text"], config)
                output.append(lead)
            else:
                errors.append({"source": lead["url"], "error": str(exc)[:200]})
    return output, errors
