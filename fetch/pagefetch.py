"""Reading job boards that publish no feed, and pulling full descriptions.

Two jobs, one module, because they are the same problem twice: fetch an HTML
page and get something useful out of it.

WHY THIS IS HEURISTIC AND NOT A SET OF HAND-WRITTEN PARSERS

Nine employers were confirmed to carry LMIC vacancies with no feed of any kind:
Last Mile Health, Living Goods, OUCRU, Ifakara, icddr,b, ICMR, DevNetJobsIndia
and others. The tempting move is nine bespoke parsers keyed to each site's CSS.
That would mean writing nine parsers against markup I have never seen, which is
the same guess-and-hope that produced fourteen dead Greenhouse tokens earlier in
this project.

So instead: harvest every link on a listing page, keep the ones that look like
job postings, and let the relevance gate and the scorer do what they already do
well. It is noisier than a bespoke parser and considerably harder to break. A
site redesign changes the noise level rather than silently returning zero.

Where a site's job URLs have an obvious shape, put a `link_pattern` regex in
config/sources.yaml and the noise drops to nothing. Run

    python3 run_refresh.py --discover https://example.org/careers

to print the link shapes on a page and work out what that regex should be.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import get, job, parse_date, strip_html, truncate

log = logging.getLogger("phjobs.pages")

# Link text that is navigation, not a vacancy.
NAV_WORDS = {
    "home", "about", "about us", "contact", "contact us", "careers", "jobs",
    "search", "login", "log in", "sign in", "register", "apply", "apply now",
    "next", "previous", "prev", "more", "read more", "view all", "see all",
    "back", "menu", "privacy", "privacy policy", "terms", "cookies", "sitemap",
    "news", "events", "blog", "donate", "our work", "who we are", "resources",
    "publications", "media", "press", "faq", "help", "support", "subscribe",
    "newsletter", "share", "facebook", "twitter", "linkedin", "instagram",
    "youtube", "english", "français", "espanol", "skip to content",
    "all jobs", "current vacancies", "vacancies", "opportunities", "openings",
}

# A vacancy title is rarely shorter than this or longer than that.
MIN_TITLE = 12
MAX_TITLE = 160

# Words that make a link very likely to be a posting when nothing else is known.
JOBBY = re.compile(
    r"\b(officer|manager|coordinator|assistant|associate|director|advisor|"
    r"adviser|specialist|consultant|analyst|fellow|researcher|scientist|"
    r"lead|head|engineer|nurse|physician|doctor|clinician|technician|"
    r"supervisor|administrator|intern|volunteer|candidate|phd|postdoc|"
    r"professor|lecturer|epidemiologist|statistician|pharmacist|midwife|"
    r"driver|logistician|accountant|programme|program|project|deputy|chief|"
    r"senior|junior|regional|country|field|technical|clinical)\b",
    re.I,
)

# Paths that are obviously not a single vacancy.
BAD_PATH = re.compile(
    r"(/(login|signin|signup|register|privacy|terms|cookie|about|contact|news|"
    r"blog|events?|donate|media|press|search|tag|category|author|feed|rss|"
    r"wp-|admin|cart|checkout)(/|$)|\.(pdf|jpg|jpeg|png|gif|svg|zip|docx?|xlsx?)$)",
    re.I,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _looks_like_job(text: str, href: str, pattern: re.Pattern | None) -> bool:
    if pattern:
        return bool(pattern.search(href))
    low = text.lower().strip(" .:-|")
    if low in NAV_WORDS or len(text) < MIN_TITLE or len(text) > MAX_TITLE:
        return False
    if BAD_PATH.search(urlparse(href).path):
        return False
    return bool(JOBBY.search(text))


def discover(url: str) -> str:
    """Print the link shapes on a page, to help write a link_pattern."""
    soup = BeautifulSoup(get(url).text, "html.parser")
    shapes: Counter = Counter()
    examples: dict[str, tuple[str, str]] = {}
    for a in soup.find_all("a", href=True):
        full = urljoin(url, a["href"])
        path = urlparse(full).path
        shape = re.sub(r"/[^/]*\d[^/]*", "/<id>", path)
        shape = re.sub(r"/[a-z0-9-]{25,}", "/<slug>", shape)
        shapes[shape] += 1
        examples.setdefault(shape, (_clean(a.get_text()), full))

    lines = [f"link shapes on {url}", ""]
    for shape, n in shapes.most_common(30):
        title, ex = examples[shape]
        lines.append(f"{n:>4}  {shape}")
        lines.append(f"      e.g. {title[:70]!r}")
        lines.append(f"           {ex[:110]}")
    return "\n".join(lines)


def harvest(sites: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Pull candidate vacancies off listing pages that publish no feed."""
    results: list[dict] = []
    status: dict[str, str] = {}

    for site in sites:
        if not site.get("enabled", True):
            status[f"page:{site.get('name')}"] = "disabled"
            continue

        name = site.get("name") or site.get("url", "?")
        url = site.get("url")
        if not url:
            status[f"page:{name}"] = "error: no url"
            continue

        pattern = None
        if site.get("link_pattern"):
            try:
                pattern = re.compile(site["link_pattern"], re.I)
            except re.error as exc:
                status[f"page:{name}"] = f"error: bad link_pattern ({exc})"
                continue

        try:
            html = get(url).text
        except Exception as exc:  # noqa: BLE001
            status[f"page:{name}"] = f"error: {exc}"
            log.info("page %s unavailable (%s)", name, exc)
            continue

        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(url).netloc
        same_host_only = site.get("same_host", True)
        seen: set[str] = set()
        found = 0
        cap = int(site.get("max_links", 60))

        for a in soup.find_all("a", href=True):
            if found >= cap:
                break
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            full = urljoin(url, href)
            if same_host_only and urlparse(full).netloc != host:
                continue
            if full in seen or full.rstrip("/") == url.rstrip("/"):
                continue

            title = _clean(a.get_text())
            if not _looks_like_job(title, full, pattern):
                continue
            # With a pattern the anchor text can still be junk like "Apply".
            if pattern and (len(title) < MIN_TITLE or title.lower() in NAV_WORDS):
                title = _clean(a.get("title") or a.get("aria-label") or title)
                if len(title) < MIN_TITLE:
                    continue

            seen.add(full)
            found += 1
            results.append(
                job(
                    source=f"Page:{name}",
                    title=title,
                    org=site.get("org") or name,
                    url=full,
                    countries=[site["country"]] if site.get("country") else [],
                    city=site.get("city", ""),
                    summary=site.get("blurb", ""),
                    hint_category=site.get("default_category", ""),
                    extra={
                        "assume_health": bool(site.get("assume_health")),
                        "_needs_body": True,
                    },
                )
            )

        if found:
            status[f"page:{name}"] = f"ok: {found} candidate links"
        else:
            status[f"page:{name}"] = (
                "error: no links looked like vacancies "
                "(page may have changed, or needs a link_pattern)"
            )

    return results, status


# --------------------------------------------------------------------------
# full descriptions
# --------------------------------------------------------------------------

_STRIP_TAGS = ["script", "style", "nav", "header", "footer", "form", "noscript", "aside"]


def _readable(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    main = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.find(class_=re.compile(r"(job|vacancy|position|content|description)", re.I))
        or soup.body
        or soup
    )
    return _clean(main.get_text(" ", strip=True))


def add_bodies(records: list[dict], known_ids: set[str], limit: int = 120) -> str:
    """Fetch the posting page for records that only have a snippet.

    Feeds hand over two lines, which is why some listings are classified thinly
    and land in the wrong category. Only records not seen on a previous run are
    fetched, and only up to `limit` of them, so a steady state costs a handful
    of requests rather than one per listing per run.
    """
    todo = [
        r for r in records
        if (r.get("_needs_body") or len(r.get("summary") or "") < 320)
        and r.get("id") not in known_ids
        and r.get("url")
    ]
    todo = todo[:limit]
    ok = fail = 0

    for rec in todo:
        try:
            text = _readable(get(rec["url"]).text)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            log.debug("body fetch failed for %s (%s)", rec.get("url"), exc)
            continue
        if len(text) < 200:
            fail += 1
            continue
        rec["_body"] = truncate(text, 8000)
        if len(text) > len(rec.get("summary") or ""):
            rec["summary"] = truncate(text, 900)
        ok += 1

    for rec in records:
        rec.pop("_needs_body", None)

    msg = f"ok: {ok} descriptions fetched, {fail} failed, {len(records) - len(todo)} skipped"
    log.info("full descriptions: %s", msg)
    return msg
