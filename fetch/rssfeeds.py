"""Config-driven RSS and Atom ingest.

Academic and PhD listings are scattered across dozens of small feeds, so this
adapter is deliberately dumb: it takes whatever config/sources.yaml names, parses
it with feedparser, and reports honestly on what came back. Adding a board is a
four-line edit to the YAML, not a code change.

feedparser is lenient about malformed XML, which matters because university feeds
frequently are. A feed that returns HTML instead of XML yields zero entries and
gets recorded as such rather than raising.
"""
from __future__ import annotations

import logging

import feedparser

from .common import get, job, parse_date, strip_html

log = logging.getLogger("phjobs.rss")


def _entry_text(entry) -> str:
    chunks = []
    for key in ("summary", "description"):
        if entry.get(key):
            chunks.append(str(entry.get(key)))
    for content in entry.get("content") or []:
        if isinstance(content, dict) and content.get("value"):
            chunks.append(str(content["value"]))
    return strip_html("\n".join(chunks))


def _entry_org(entry) -> str:
    for key in ("author", "publisher", "source"):
        value = entry.get(key)
        if isinstance(value, dict):
            value = value.get("title") or value.get("name")
        if value:
            return str(value).strip()
    for tag in entry.get("tags") or []:
        term = tag.get("term") if isinstance(tag, dict) else None
        if term and len(str(term)) < 80:
            return str(term).strip()
    return ""


def fetch(feeds: list[dict]) -> tuple[list[dict], dict[str, str]]:
    results: list[dict] = []
    status: dict[str, str] = {}

    for spec in feeds:
        if not spec.get("enabled", True):
            status[f"rss:{spec.get('name')}"] = "disabled"
            continue

        name = spec.get("name") or spec.get("url", "feed")
        url = spec.get("url")
        if not url:
            status[f"rss:{name}"] = "error: no url"
            continue

        # Fetch through the shared session so the User-Agent and retry policy
        # apply; several feeds refuse feedparser's default agent.
        try:
            raw = get(url).content
        except Exception as exc:  # noqa: BLE001
            status[f"rss:{name}"] = f"error: {exc}"
            log.info("feed %s unavailable (%s)", name, exc)
            continue

        parsed = feedparser.parse(raw)
        entries = parsed.get("entries") or []
        if not entries:
            note = "returned 0 entries"
            if parsed.get("bozo"):
                note += f" (parse warning: {parsed.get('bozo_exception')})"
            status[f"rss:{name}"] = f"error: {note}"
            continue

        feed_title = (parsed.get("feed") or {}).get("title") or name

        for entry in entries:
            link = entry.get("link") or ""
            if not link:
                continue
            body = _entry_text(entry)
            results.append(
                job(
                    source=f"RSS:{name}",
                    title=entry.get("title") or "",
                    org=_entry_org(entry) or feed_title,
                    url=link,
                    posted=parse_date(
                        entry.get("published_parsed")
                        or entry.get("updated_parsed")
                        or entry.get("published")
                        or entry.get("updated")
                    ),
                    summary=body,
                    hint_category=spec.get("default_category", ""),
                    extra={"_body": body},
                )
            )

        status[f"rss:{name}"] = f"ok: {len(entries)} entries"

    return results, status
