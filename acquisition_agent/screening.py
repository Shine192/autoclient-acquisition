"""Transparent job checks. Unknown eligibility is never treated as worldwide."""
import re
from datetime import datetime, timezone


def company_country(text, countries):
    aliases = {"United States": ["United States", "USA"], "United Kingdom": ["United Kingdom", "UK"]}
    # Prefer a labelled headquarters block. If it is ambiguous, do not search
    # travel requirements, customer countries or employee eligibility instead.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    context = []
    for i, line in enumerate(lines):
        match = re.match(r"^(?:headquarters|head office|company location|registered office)\s*:\s*(.*)$", line, re.I)
        if match:
            context.append(match.group(1) or (lines[i + 1] if i + 1 < len(lines) else ""))
    if not context:
        context = re.findall(r"(?:based|headquartered|head office|offices?)\s+(?:in|at)\s+([^.!?\n]+)", text, re.I)
    candidates = "\n".join(context)
    matches = [country for country in dict.fromkeys(countries) if any(re.search(r"(?<![\w./@-])" + re.escape(alias) + r"(?![\w/@-]|\.\w)", candidates, re.I) for alias in aliases.get(country, [country]))]
    return matches[0] if len(matches) == 1 else ""


def role_conflict(title):
    title = title.lower()
    explicit_fit = re.search(r"email.{0,25}design|design.{0,25}email|klaviyo.{0,25}(?:specialist|designer|builder|expert)", title)
    broad_role = re.search(r"growth (?:lead|manager)|demand generation|(?:shopify|software|full.stack|backend|front.end) developer|marketing (?:manager|director)|head of marketing|paid (?:ads|media)", title)
    return bool(broad_role and not explicit_fit)


def eligibility_conflicts(text, weekly_capacity):
    text = " ".join(text.lower().split())
    conflicts = []
    if weekly_capacity <= 20 and re.search(r"(?:type|hours|schedule|employment(?: type)?|commitment)\s*:.{0,100}\bfull[- ]time\b|(?:able to work in|requires?|seeking)\s+(?:an?\s+)?full[- ]time(?:\s+remote)?\s+(?:role|position|contractor|commitment)|\bfull[- ]time\s+(?:position|role|commitment)\b", text):
        conflicts.append("Full-time commitment conflicts with availability of up to 20 hours/week")
    for match in re.finditer(r"(?:must (?:reside|be based|live) in|(?:applicants|candidates|residents) (?:must be |from )?|open across)\s+([^.\n]{2,100})", text):
        region = match.group(1)
        if re.search(r"\b(?:europe|americas|united states|usa|uk|united kingdom|australia|new zealand|north america)\b", region) and not re.search(r"\b(?:asia|thailand|worldwide|globally|anywhere)\b", region):
            conflicts.append("Advertised applicant region excludes Thailand")
            break
    if re.search(r"\b(?:us|uk|europe|australia|new zealand)[- ]only\b", text):
        conflicts.append("Advertised applicant region excludes Thailand")
    return list(dict.fromkeys(conflicts))


def freshness_reason(posted_at, max_days=60, clock=None):
    if not posted_at:
        return "", "Posting date and vacancy status need review"
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age = ((clock or datetime.now(timezone.utc)) - posted).total_seconds() / 86400
    except (ValueError, TypeError):
        return "", "Posting date could not be parsed"
    if age > max_days:
        return "Posting is older than the " + str(max_days) + "-day discovery window; current opening is unverified", ""
    if age < -1:
        return "", "Posting date is in the future; verify source"
    return "", ""


def workload(text):
    ranges = re.findall(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:/|per\s+)(?:week|wk)", text, re.I)
    singles = re.findall(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:/|per\s+)(?:week|wk)", text, re.I)
    values = [float(b) for a, b in ranges] + [float(v) for v in singles]
    if not values:
        return None
    return max(values)
