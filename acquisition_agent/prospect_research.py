"""Bounded official-page discovery and shared evidence-first research guidance."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

RESEARCH_STRATEGY = (
    'RESEARCH PRIORITIES: Establish audience fit before drafting: published email/Klaviyo services for an agency, '
    'or a relevant product and email-design use case for a brand. Distinguish an advertised job from a prospective client. '
    'Read a relevant service/project page and the official contact page, retaining each exact URL and quotation. '
    'Choose one specific business observation and connect it to one useful contribution; personal trivia is unnecessary. '
    'A recent announcement is optional and must have a verified date; never call an undated page recent. '
    'Record missing evidence as unknown rather than completing a quota with weak prospects. '
    'Official contact purpose must support the intended message. Finder tools, directories and LinkedIn can suggest '
    'where to research; they do not replace published organizational contact evidence or prove deliverability, consent or interest. '
    'Never guess email patterns, buy lists, contact multiple people at the same company, or substitute support/press/HR '
    'for a business introduction. Preserve specifically authorized work-enquiry routes. '
    'Do not infer budget, hiring or workload from company size, country or a fit score. '
    'Keep research bounded to the supplied page and spending limits; no extra tools or purchases.'
)


class ResearchText(str):
    """String-compatible visible text with a small set of official navigation links."""
    def __new__(cls, text, links=()):
        value = super().__new__(cls, text)
        value.links = tuple(links)
        return value


def official_links(html, url):
    """Only HTTPS links on the exact host; no query endpoints or protected contacts."""
    found = []
    origin = urlsplit(url)

    class Links(HTMLParser):
        hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style', 'noscript'):
                self.hidden += 1
            if self.hidden or tag != 'a' or len(found) >= 100:
                return
            href = dict(attrs).get('href', '')
            try:
                target = urlsplit(urljoin(url, href))
                if (target.scheme != 'https' or target.hostname != origin.hostname or
                        target.username or target.password or target.port not in (None, 443) or
                        target.query or not target.path or
                        not re.search(r'contact|about|services?|klaviyo|email|retention|case-stud|our-work|projects?', target.path, re.I) or
                        re.search(r'login|logout|unsubscribe|cdn-cgi|privacy|terms|\.(pdf|zip|png|jpg)$', target.path, re.I)):
                    return
                clean = urlunsplit((target.scheme, target.netloc, target.path, '', ''))
                if clean not in found:
                    found.append(clean)
            except ValueError:
                return

        def handle_endtag(self, tag):
            if tag in ('script', 'style', 'noscript'):
                self.hidden = max(0, self.hidden - 1)

    parser = Links()
    parser.feed(html)
    return found


def supporting_pages(url, links):
    """Prefer an actual contact route plus service evidence within two extra reads."""
    origin = urlsplit(url)
    root = origin.scheme + '://' + origin.netloc
    contacts = [x for x in links if re.search(r'contact', urlsplit(x).path, re.I)]
    services = [x for x in links if re.search(r'klaviyo|email|retention|case-stud|our-work|projects?|services?', urlsplit(x).path, re.I)]
    about = [x for x in links if re.search(r'about', urlsplit(x).path, re.I)]
    choices = (contacts or [root + '/contact']) + services + about + [root + '/about']
    # Contact evidence and service relevance each receive one slot when available.
    ordered = choices[:1] + services + about + choices[1:]
    seen = {url.rstrip('/')}
    result = []
    for page in ordered:
        if page.rstrip('/') not in seen:
            seen.add(page.rstrip('/'))
            result.append(page)
        if len(result) == 2:
            break
    return result
