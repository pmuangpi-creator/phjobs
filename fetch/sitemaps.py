"""XML sitemap ingest, for boards that publish a sitemap but no feed.

WHY THIS EXISTS

The doctoral track has a geography problem the jobs board does not. Most of the
world's fully funded PhD posts that are actually employment contracts sit in
the Netherlands and the Nordics, and the two platforms carrying them publish no
RSS at all: Varbi runs the Swedish universities, AcademicTransfer runs the Dutch
academic market. Both publish XML sitemaps, which is a machine-readable format
offered to crawlers on purpose, so there is nothing to scrape and nothing to
guess at.

TWO SHAPES

varbi   feeds.varbi.com/sitemap/<customer>/ returns a sitemap whose <url>
        entries carry meta_title, meta_city, meta_ends, meta_customer_fullname
        and meta_description alongside <loc>. That is a full record, better than
        most RSS feeds, and no follow-up page fetch is needed.

plain   an ordinary <urlset> of <loc> elements, as AcademicTransfer publishes at
        /sitemap-vacancies.xml. There is no title field, so the title comes from
        the URL slug and the description is filled in later by the existing
        full-description step. Because that step costs one request per listing,
        `include_pattern` filters the URL list first: the doctoral track wants
        the promovendus and PhD slugs, not all 500 Dutch academic vacancies.

Namespaces are stripped before matching, so a platform that moves its meta_*
fields into a namespace of its own keeps working.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from .common import get, job, parse_date, strip_html

log = logging.getLogger("phjobs.sitemap")

_NS = re.compile(r"^\{[^}]*\}")
_SLUG_JUNK = re.compile(r"[-_+]+")


def _tag(element) -> str:
    return _NS.sub("", element.tag).lower()


def _fields(node) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in node:
        name = _tag(child)
        text = (child.text or "").strip()
        if text and name not in out:
            out[name] = text
    return out


def _title_from_url(url: str) -> str:
    """AcademicTransfer-style /jobs/361524/assistant-professor-on-x/ -> a title.

    Returns "" when the last path segment is numeric or too short to be a title,
    which is the signal to skip the record rather than publish a row reading
    "361524".
    """
    path = urlparse(url).path.rstrip("/")
    slug = unquote(path.rsplit("/", 1)[-1]) if path else ""
    if not slug or slug.isdigit() or len(slug) < 8:
        return ""
    words = [w for w in _SLUG_JUNK.split(slug) if w]
    if len(words) < 2:
        return ""
    return " ".join(words).strip().capitalize()


def _varbi_records(root, spec: dict) -> list[dict]:
    name = spec.get("name") or "sitemap"
    default_country = spec.get("country") or ""
    records: list[dict] = []

    for node in root:
        if _tag(node) != "url":
            continue
        f = _fields(node)
        url = f.get("loc") or ""
        title = f.get("meta_title") or _title_from_url(url)
        if not url or not title:
            continue

        body = strip_html(f.get("meta_description") or f.get("meta_summary") or "")
        country = f.get("meta_country") or f.get("meta_country_ad") or default_country
        records.append(
            job(
                source=f"Sitemap:{name}",
                title=title,
                org=f.get("meta_customer_fullname") or f.get("meta_customer") or spec.get("org", ""),
                url=url,
                countries=[country] if country else [],
                city=f.get("meta_city", ""),
                posted=parse_date(f.get("meta_start") or f.get("lastmod")),
                deadline=parse_date(f.get("meta_ends")),
                summary=body,
                contract=f.get("meta_type", ""),
                hint_category=spec.get("default_category", ""),
                extra={
                    "_body": body,
                    # A meta_description of two sentences is not enough to judge
                    # funding on, and funding is the whole point of this track.
                    "_needs_body": len(body) < 600,
                    "assume_health": bool(spec.get("assume_health")),
                    "assume_funding": spec.get("assume_funding", ""),
                },
            )
        )
    return records


def _plain_records(root, spec: dict) -> list[dict]:
    name = spec.get("name") or "sitemap"
    country = spec.get("country") or ""
    include = spec.get("include_pattern") or ""
    exclude = spec.get("exclude_pattern") or ""
    limit = int(spec.get("max_items", 400))

    inc = re.compile(include, re.I) if include else None
    exc = re.compile(exclude, re.I) if exclude else None

    records: list[dict] = []
    for node in root:
        if _tag(node) != "url":
            continue
        f = _fields(node)
        url = f.get("loc") or ""
        if not url:
            continue
        if inc and not inc.search(url):
            continue
        if exc and exc.search(url):
            continue
        title = _title_from_url(url)
        if not title:
            continue
        records.append(
            job(
                source=f"Sitemap:{name}",
                title=title,
                org=spec.get("org", ""),
                url=url,
                countries=[country] if country else [],
                posted=parse_date(f.get("lastmod")),
                hint_category=spec.get("default_category", ""),
                # No description at all in a plain sitemap. The full-description
                # step fills it in on the first run a listing appears, and never
                # again.
                extra={
                    "_needs_body": True,
                    "assume_health": bool(spec.get("assume_health")),
                    "assume_funding": spec.get("assume_funding", ""),
                },
            )
        )
        if len(records) >= limit:
            break
    return records


def harvest(sites: list[dict]) -> tuple[list[dict], dict[str, str]]:
    results: list[dict] = []
    status: dict[str, str] = {}

    for spec in sites or []:
        name = spec.get("name") or spec.get("url", "sitemap")
        key = f"sitemap:{name}"
        if not spec.get("enabled", True):
            status[key] = "disabled"
            continue
        url = spec.get("url")
        if not url:
            status[key] = "error: no url"
            continue

        try:
            raw = get(url).content
        except Exception as exc:  # noqa: BLE001
            status[key] = f"error: {exc}"
            log.info("sitemap %s unavailable (%s)", name, exc)
            continue

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            status[key] = f"error: not XML ({exc})"
            continue

        if _tag(root) == "sitemapindex":
            status[key] = "error: this is a sitemap index, point at a child sitemap"
            continue

        flavour = (spec.get("flavour") or "plain").lower()
        try:
            got = _varbi_records(root, spec) if flavour == "varbi" else _plain_records(root, spec)
        except Exception as exc:  # noqa: BLE001
            status[key] = f"error: {exc}"
            continue

        results.extend(got)
        status[key] = f"ok: {len(got)} entries" if got else "error: returned 0 usable entries"

    return results, status
