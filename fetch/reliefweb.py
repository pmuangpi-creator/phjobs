"""ReliefWeb jobs.

The anchor source. ReliefWeb aggregates vacancies posted by roughly four
thousand humanitarian and development organisations, UN agencies included, and
publishes them through a documented, key-free API (https://apidoc.reliefweb.int).
It only lists jobs that are still open, so there is no need to filter closed
postings out here.

Deliberately no server-side theme filter. ReliefWeb's taxonomy puts plenty of
health-adjacent work under Coordination, Protection or Education, and the
relevance gate in pipeline/classify.py is both broader and easier to tune than
their facet list. Fetch wide, filter locally.

VERSION HISTORY, because this bit us once already: the v1 endpoint was
decommissioned and now answers 410 Gone. v2 is documented as fully compatible
with v1, so the field names and request shape below are unchanged; only the base
URL moved. Since 1 November 2025 ReliefWeb also asks that the appname be
pre-approved through a form linked from https://apidoc.reliefweb.int/parameters.
See the note in config/sources.yaml.
"""
from __future__ import annotations

import logging

from .common import get, job, parse_date, post, strip_html

log = logging.getLogger("phjobs.reliefweb")

FIELDS = [
    "id",
    "title",
    "body",
    "date.created",
    "date.closing",
    "source.name",
    "source.shortname",
    "country.name",
    "city.name",
    "career_categories.name",
    "theme.name",
    "type.name",
    "experience.name",
    "url_alias",
    "url",
]


def _names(value) -> list[str]:
    """ReliefWeb returns taxonomy terms as a list of dicts, a bare dict, or nothing."""
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    out = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("shortname")
            if name:
                out.append(str(name).strip())
        elif item:
            out.append(str(item).strip())
    return out


def _first(value) -> str:
    names = _names(value)
    return names[0] if names else ""


def fetch(cfg: dict) -> list[dict]:
    endpoint = cfg.get("endpoint", "https://api.reliefweb.int/v2/jobs")
    appname = cfg.get("appname", "phjobs-aggregator")
    page_size = int(cfg.get("page_size", 500))
    max_pages = int(cfg.get("max_pages", 4))

    results: list[dict] = []
    offset = 0

    for page in range(max_pages):
        payload = {
            "offset": offset,
            "limit": page_size,
            "sort": ["date.created:desc"],
            "fields": {"include": FIELDS},
        }
        try:
            resp = post(
                endpoint,
                params={"appname": appname},
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            # A POST body is the documented approach, but some intermediaries
            # mangle it. Fall back to a plain GET for the first page so a run
            # still produces something.
            log.warning("POST page %s failed (%s); trying GET", page, exc)
            try:
                resp = get(
                    endpoint,
                    params={
                        "appname": appname,
                        "offset": offset,
                        "limit": min(page_size, 200),
                        "profile": "full",
                        "sort[]": "date.created:desc",
                    },
                )
                data = resp.json()
            except Exception as exc2:  # noqa: BLE001
                raise RuntimeError(f"ReliefWeb page {page} failed: {exc2}") from exc2

        items = data.get("data") or []
        if not items:
            break

        for item in items:
            f = item.get("fields") or {}
            body = strip_html(f.get("body") or "")
            dates = f.get("date") or {}
            url = f.get("url_alias") or f.get("url") or ""
            if not url and item.get("id"):
                url = f"https://reliefweb.int/node/{item['id']}"

            results.append(
                job(
                    source="ReliefWeb",
                    title=f.get("title") or "",
                    org=_first(f.get("source")),
                    url=url,
                    countries=_names(f.get("country")),
                    city=_first(f.get("city")),
                    posted=parse_date(dates.get("created")),
                    deadline=parse_date(dates.get("closing")),
                    summary=body,
                    contract=_first(f.get("type")),
                    seniority=_first(f.get("experience")),
                    extra={
                        "rw_categories": _names(f.get("career_categories")),
                        "rw_themes": _names(f.get("theme")),
                        "_body": body,
                    },
                )
            )

        total = int((data.get("totalCount") or data.get("count") or 0))
        offset += len(items)
        if len(items) < page_size or (total and offset >= total):
            break

    log.info("ReliefWeb: %s jobs", len(results))
    return results
