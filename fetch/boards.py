"""Greenhouse and Lever job boards.

Both run open, key-free JSON endpoints that exist so that an employer's own
website can render its careers page. Reading them is the intended use, and each
call is one request per organisation per run.

Worth adding later: Workday (POST to /wday/cxs/{tenant}/{site}/jobs), SmartRecruiters
(api.smartrecruiters.com/v1/companies/{id}/postings) and Ashby. Several large
INGOs sit on those three, and each is maybe forty lines in this same shape.
"""
from __future__ import annotations

import logging

from .common import get, job, parse_date, strip_html, truncate

log = logging.getLogger("phjobs.boards")

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{company}?mode=json&limit=200"


def _pretty(token: str) -> str:
    return token.replace("-", " ").replace("_", " ").title()


def _split_location(text: str) -> tuple[list[str], str]:
    """'Nairobi, Kenya' -> (['Kenya'], 'Nairobi'). Best effort, no gazetteer."""
    text = (text or "").strip()
    if not text:
        return [], ""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) == 1:
        return [parts[0]], ""
    return [parts[-1]], ", ".join(parts[:-1])


def fetch_greenhouse(tokens: list[str]) -> tuple[list[dict], dict[str, str]]:
    results: list[dict] = []
    status: dict[str, str] = {}

    for token in tokens:
        try:
            data = get(GREENHOUSE.format(token=token)).json()
        except Exception as exc:  # noqa: BLE001
            status[f"greenhouse:{token}"] = f"error: {exc}"
            log.info("greenhouse %s unavailable (%s)", token, exc)
            continue

        jobs = data.get("jobs") or []
        org = _pretty(token)
        for j in jobs:
            content = strip_html(j.get("content") or "")
            loc = ((j.get("location") or {}).get("name")) or ""
            countries, city = _split_location(loc)
            # Greenhouse sometimes carries a nicer company name in the metadata.
            for meta in j.get("metadata") or []:
                if str(meta.get("name", "")).lower() in {"organization", "company"} and meta.get("value"):
                    org = str(meta["value"])
                    break
            results.append(
                job(
                    source=f"Greenhouse:{token}",
                    title=j.get("title") or "",
                    org=org,
                    url=j.get("absolute_url") or "",
                    countries=countries,
                    city=city,
                    posted=parse_date(j.get("updated_at") or j.get("created_at")),
                    summary=content,
                    extra={"_body": content},
                )
            )
        status[f"greenhouse:{token}"] = f"ok: {len(jobs)} postings"

    return results, status


def fetch_lever(companies: list[str]) -> tuple[list[dict], dict[str, str]]:
    results: list[dict] = []
    status: dict[str, str] = {}

    for company in companies:
        try:
            data = get(LEVER.format(company=company)).json()
        except Exception as exc:  # noqa: BLE001
            status[f"lever:{company}"] = f"error: {exc}"
            log.info("lever %s unavailable (%s)", company, exc)
            continue

        if not isinstance(data, list):
            status[f"lever:{company}"] = "error: unexpected payload shape"
            continue

        for j in data:
            cats = j.get("categories") or {}
            loc = cats.get("location") or ""
            countries, city = _split_location(loc)
            body = strip_html(j.get("descriptionPlain") or j.get("description") or "")
            for section in j.get("lists") or []:
                body += "\n" + strip_html(section.get("text", "")) + " " + strip_html(section.get("content", ""))
            results.append(
                job(
                    source=f"Lever:{company}",
                    title=j.get("text") or "",
                    org=_pretty(company),
                    url=j.get("hostedUrl") or j.get("applyUrl") or "",
                    countries=countries,
                    city=city,
                    posted=parse_date(j.get("createdAt")),
                    summary=body,
                    contract=cats.get("commitment") or "",
                    extra={"_body": truncate(body, 6000)},
                )
            )
        status[f"lever:{company}"] = f"ok: {len(data)} postings"

    return results, status
