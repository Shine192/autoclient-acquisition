"""Optional external services. Keys come from environment, never project config."""
import json
import os
import time
from pathlib import Path
from . import notion_compat as compat
from .network import api_json


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError("Set " + name + " in your local environment or .env file")
    return value


def generate(prompt, provider):
    model = require_env("AI_MODEL")
    if provider == "anthropic":
        r = api_json("https://api.anthropic.com/v1/messages", payload={"model": model, "max_tokens": 1600, "messages": [{"role": "user", "content": prompt}]}, headers={"x-api-key": require_env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    elif provider == "openai":
        r = api_json("https://api.openai.com/v1/responses", payload={"model": model, "input": prompt, "max_output_tokens": 2000}, headers={"Authorization": "Bearer " + require_env("OPENAI_API_KEY")})
        text = "".join(b.get("text", "") for o in r.get("output", []) for b in o.get("content", []) if b.get("type") == "output_text")
    else:
        raise ValueError("Choose manual, openai or anthropic")
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("AI did not return valid JSON; no draft saved") from None


def search(query, limit):
    r = api_json("https://api.firecrawl.dev/v2/search", payload={"query": query, "limit": min(limit, 10), "sources": ["web"]}, headers={"Authorization": "Bearer " + require_env("FIRECRAWL_API_KEY")})
    if not r.get("success", True):
        raise ValueError("Search provider reported failure")
    data = r.get("data", {})
    return data.get("web", []) if isinstance(data, dict) else data


def rich(text):
    text = str(text or "")
    return [{"type": "text", "text": {"content": text[i:i + 1900]}} for i in range(0, min(len(text), 19000), 1900)]


def text_value(prop):
    return "".join(x.get("plain_text", x.get("text", {}).get("content", "")) for x in prop.get(prop.get("type"), []))


class Notion:
    def __init__(self):
        path=Path(__file__).resolve().parent.parent/'config/notion_connection.json'
        self.connection=json.loads(path.read_text()) if path.exists() else {}
        preferences=path.with_name('preferences.json')
        if not self.connection and preferences.exists() and json.loads(preferences.read_text()).get('notion_leads_source_id')==compat.SOURCE:
            self.connection={'source_id':compat.SOURCE}
        self._original_pages=set()
        self.headers = {"Authorization": "Bearer " + require_env("NOTION_TOKEN"), "Notion-Version": "2025-09-03"}

    def request(self, path, method="POST", data=None):
        from copy import deepcopy
        data=deepcopy(data)
        parts=path.split('/')
        is_source=len(parts)>1 and parts[0]=='data_sources' and parts[1]==compat.SOURCE
        is_original=is_source
        if path=='pages' and data:
            is_original=data.get('parent',{}).get('data_source_id')==compat.SOURCE
        elif parts[0]=='pages' and len(parts)>1 and method!='GET':
            if parts[1] not in self._original_pages:
                self.request('pages/'+parts[1],'GET')
            is_original=parts[1] in self._original_pages
        if is_original and data:
            if 'properties' in data:data['properties']=compat.encode_props(data['properties'])
            if 'filter' in data:data['filter']=compat.encode_filter(data['filter'])
        # Sequential calls stay below the typical connection request rate.
        time.sleep(0.36)
        result=api_json("https://api.notion.com/v1/" + path, method, data, self.headers)
        def decode(page, force=False):
            p=page.get('properties',{})
            if force or compat.original(p):
                page=deepcopy(page)
                if page.get('object')=='page' or 'NAME' in p:
                    self._original_pages.add(page['id']);page['_outreach_original']=True
                page['properties']=compat.decode_props(p)
            return page
        if 'results' in result:
            result={**result,'results':[decode(page,is_source) for page in result['results']]}
        elif 'properties' in result:
            result=decode(result,is_source or is_original)
        return result

    def assert_contact_available(self, lead, source=None):
        source=source or self.connection.get('source_id')
        if source!=compat.SOURCE:return
        for page in self.query(source):
            if page['id'].replace('-','')==(lead.get('notion_page_id') or '').replace('-',''):continue
            if compat.contact_match(page,lead):
                raise ValueError('Existing Outreach record matches this company or email; preserved without overwrite or repeat outreach: '+page['id'])

    def query(self, source, filters=None):
        cursor = None
        while True:
            data = {"page_size": 100}
            if cursor:
                data["start_cursor"] = cursor
            if filters:
                data["filter"] = filters
            result = self.request("data_sources/" + source + "/query", data=data)
            yield from result.get("results", [])
            if not result.get("has_more"):
                return
            cursor = result["next_cursor"]

    def find_lead(self, source, key):
        rows = list(self.query(source, {"property": "Deduplication Key", "rich_text": {"equals": key}}))
        if len(rows) > 1:
            raise ValueError("Duplicate Notion rows require review")
        return rows[0] if rows else None

    def save_lead(self, source, lead):
        page = self.request("pages/" + lead["notion_page_id"], "GET") if lead.get("notion_page_id") else self.find_lead(source, lead["id"])
        self.assert_contact_available(dict(lead, notion_page_id=page['id']) if page else lead, source)
        if page:
            # Notion becomes the editor after first sync. Never silently overwrite edits.
            props = page["properties"]
            if page.get('_outreach_original') and text_value(props.get('Deduplication Key',{}))!=lead['id']:
                raise ValueError('Existing Outreach row is not owned by this research record; history preserved')
            remote_status = props.get("STATUS", {}).get("status", {}).get("name", "Needs Review")
            if lead.get("starter_seed"):
                # An initial source pack must not overwrite a draft already edited in Notion.
                lead["draft_dirty"] = False
            if lead.get("draft_dirty"):
                if remote_status in ("Sent", "Sending", "Replied", "Interview", "Won", "Closed", "Do Not Contact", "Rejected", "Rejected") or props.get("Do Not Contact", {}).get("checkbox"):
                    raise ValueError("Notion row is closed, contacted or suppressed; refusing draft overwrite")
                draft = lead["draft"]
                self.request("pages/" + page["id"], "PATCH", {"properties": {"email SUBJECT": {"rich_text": rich(draft["subject"])}, "email body": {"rich_text": rich(draft["body"])}, "STATUS": {"status": {"name": "Draft"}}, "Approved": {"checkbox": False}, "Research Notes": {"rich_text": rich(research_notes(lead))}, **({"Error": {"rich_text": []}} if lead.get("draft_repaired") else {})}})
                remote_status = "Draft"
            lead["notion_page_id"] = page["id"]
            lead["status"] = remote_status
            lead["draft_dirty"] = False
            return
        result = self.request("pages", data={"parent": {"type": "data_source_id", "data_source_id": source}, "properties": lead_properties(lead)})
        lead["notion_page_id"] = result["id"]
        lead["draft_dirty"] = False

    def session_update(self, page_id, status, message, count=None):
        props = {"STATUS": {"status": {"name": status}}, "Message": {"rich_text": rich(message)}}
        if count is not None:
            props["Found"] = {"number": count}
        self.request("pages/" + page_id, "PATCH", {"properties": props})


def research_notes(lead):
    return json.dumps({"draft_error":lead.get("draft_error", ""), "target_session":lead.get("target_session"), "location_city":lead.get("location_city", ""), "industry":lead.get("industry", ""), "target_evidence":lead.get("target_evidence", {}), "target_reasons":lead.get("target_reasons", []), "job_url": lead["url"], "source": lead.get("research_source_url", lead["url"]), "research_level": lead.get("research_level", "Supplied text"), "research_warning": lead.get("research_warning", ""), "checked_at": lead.get("checked_at", ""), "country_source_url": lead.get("country_source_url", ""), "country_evidence": lead.get("country_evidence", ""), "collected": lead["discovered_at"], "review_reasons": lead.get("reasons", []), "source_excerpt": lead.get("source_text", "")[:5000], "source_documents": lead.get("source_documents", []), "email_candidates": lead.get("email_candidates", []), "personalization_evidence": lead.get("draft", {}).get("evidence", []), "ai_prompt_file": lead.get("prompt_file", ""), "demo": lead.get("is_demo", False)}, ensure_ascii=False, indent=2)


def lead_properties(lead):
    props = {"Name": {"title": rich(("[DEMO] " if lead.get("is_demo") else "") + (lead.get("company") or lead["title"]))}, "STATUS": {"status": {"name": lead["status"]}}, "Role": {"rich_text": rich(lead["title"])}, "COUNTRY": {"rich_text": rich(lead.get("country", ""))}, "Opportunity Type": {"select": {"name": lead["kind"]}}, "Job URL": {"url": lead["url"]}, "WEBSITE": {"url": lead.get("website") or None}, "EMAIL": {"email": lead.get("email") or None}, "Contact Source URL": {"url": lead.get("contact_source_url") or None}, "Research Notes": {"rich_text": rich(research_notes(lead))}, "Deduplication Key": {"rich_text": rich(lead["id"])}, "Match Score": {"number": lead["score"]}, "Approved": {"checkbox": False}, "Do Not Contact": {"checkbox": lead["status"] == "Do Not Contact"}, "Remote Eligibility": {"select": {"name": lead.get("remote_eligibility", "Unknown")}}}
    if lead.get("type") in ("Agency", "Brand", "Start-up"):
        props["Type"] = {"select": {"name": lead["type"]}}
    if lead.get('target_session'):
        props.update({'Discovery Session':{'rich_text':rich(lead['target_session']['id'])},
                      'Target City':{'rich_text':rich(lead.get('location_city',''))},
                      'Industry':{'rich_text':rich(lead.get('industry_label',lead.get('industry','')))},
                      'Targeting Reviewed':{'checkbox':False}})
    rate = lead.get("rate_per_email")
    budget = "Unknown" if rate is None or lead.get("currency") != "USD" else ("Below Minimum" if rate < 20 else "Above Range" if rate > 30 else "In Range")
    props["Budget Status"] = {"select": {"name": budget}}
    if rate is not None:
        props["Rate Per Email"] = {"number": rate}
        props["Budget Currency"] = {"rich_text": rich(lead.get("currency"))}
    if lead.get("hours_per_week") is not None:
        props["Hours Per Week"] = {"number": lead["hours_per_week"]}
    if lead.get("draft_error"):
        props["Error"] = {"rich_text": rich("Draft needs repair: " + lead["draft_error"])}
    if lead.get("draft"):
        props["email SUBJECT"] = {"rich_text": rich(lead["draft"]["subject"])}
        props["email body"] = {"rich_text": rich(lead["draft"]["body"])}
    props.update({
        'Fit Reasons': {'rich_text': rich('\n'.join(lead.get('reasons', [])))},
        'Remote Restrictions': {'rich_text': rich('Unknown; review source for Thailand eligibility and timezone overlap' if lead.get('remote_eligibility') != 'Confirmed' else 'Source states international/worldwide freelance eligibility; check remaining requirements')},
        'Compensation': {'rich_text': rich(lead.get('compensation', 'Unknown' if rate is None else str(rate) + ' ' + lead.get('currency', 'Unknown') + ' per email'))},
        'Selected Offer': {'rich_text': rich('paid_test')},
        'Offer Reason': {'rich_text': rich('One bounded paid Figma design test; no unpaid commitment. Follow advertised application instructions first.')},
        'Application Route': {'rich_text': rich('Needs review: email vs official portal' if lead['kind'] == 'Posted Job' else 'Business introduction; verify contact purpose')},
    })
    if lead.get('posted_at'):
        from datetime import datetime
        try:
            date = datetime.fromisoformat(lead['posted_at'].replace('Z', '+00:00'))
            props['Posting Date'] = {'date': {'start': date.isoformat()}}
        except (ValueError, TypeError):
            pass
    return props
