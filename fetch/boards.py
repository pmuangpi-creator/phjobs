"""Greenhouse and Lever job boards.

Both run open, key-free JSON endpoints that exist so that an employer's own
website can render its careers page. Reading them is the intended use, and each
call is one request per organisation per run.

Workday and SmartRecruiters are here too, for the same reason. A survey of where
the large global health employers actually keep their vacancies found almost none
of them on Greenhouse or Lever: PATH, FHI 360 and Management Sciences for Health
are on Workday, PSI is on SmartRecruiters, and CHAI, Jhpiego, Vital Strategies,
IntraHealth, Population Council, Abt and Palladium are spread across iCIMS,
Taleo, UKG, Paylocity, Oracle Fusion and Cornerstone. Workday and SmartRecruiters
were worth adapters because one adapter each covers several employers. The rest
are JS-rendered and would need a browser, which is out of scope for a static
build.
"""
from __future__ import annotations

import logging

from .common import get, job, parse_date, strip_html, truncate

log = logging.getLogger("phjobs.boards")

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{company}?mode=json&limit=200"
WORKDAY = "https://{host}/wday/cxs/{tenant}/{site}/jobs"
SMARTRECRUITERS = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
BAMBOOHR = "https://{sub}.bamboohr.com/careers/list"
WORKABLE = "https://apply.workable.com/api/v1/widget/accounts/{account}?details=true"


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


def fetch_workday(sites: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Workday's own careers-page backend.

    Undocumented but stable and identical across tenants: a POST returning
    {total, jobPostings:[{title, externalPath, locationsText, postedOn}]}. The
    list carries no description, so the relevance gate would see only the title.
    That is what assume_health in the config is for -- these are health
    organisations, so their whole board is in scope and the negative weights in
    profile.yaml push the finance and IT roles to the bottom on their own.
    """
    results: list[dict] = []
    status: dict[str, str] = {}

    for site in sites:
        name = site.get("name") or site.get("tenant", "?")
        host, tenant, path = site.get("host"), site.get("tenant"), site.get("site")
        if not (host and tenant and path):
            status[f"workday:{name}"] = "error: needs host, tenant and site"
            continue

        url = WORKDAY.format(host=host, tenant=tenant, site=path)
        found = 0
        try:
            for offset in range(0, int(site.get("max_results", 200)), 20):
                data = post(
                    url,
                    json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                ).json()
                postings = data.get("jobPostings") or []
                if not postings:
                    break
                for p in postings:
                    ext = p.get("externalPath") or ""
                    loc = p.get("locationsText") or ""
                    countries, city = _split_location(loc.split(" and ")[0])
                    bullets = " ".join(str(b) for b in (p.get("bulletFields") or []))
                    results.append(
                        job(
                            source=f"Workday:{name}",
                            title=p.get("title") or "",
                            org=site.get("org") or _pretty(tenant),
                            url=f"https://{host}/{path}{ext}" if ext else f"https://{host}/{path}",
                            countries=countries,
                            city=city,
                            posted=parse_date(p.get("startDate") or p.get("postedOn")),
                            summary=f"{loc}. {bullets}".strip(". "),
                            extra={"assume_health": bool(site.get("assume_health"))},
                        )
                    )
                    found += 1
                if len(postings) < 20 or found >= int(data.get("total") or 0):
                    break
            status[f"workday:{name}"] = f"ok: {found} postings"
        except Exception as exc:  # noqa: BLE001
            status[f"workday:{name}"] = f"error: {exc}"
            log.info("workday %s unavailable (%s)", name, exc)

    return results, status


def fetch_smartrecruiters(companies: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """SmartRecruiters' documented, key-free postings API.

    The list endpoint gives title and location but no description. Fetching each
    posting's detail would mean one request per vacancy per run, which is more
    traffic than this is worth, so assume_health carries these the same way it
    carries Workday.
    """
    results: list[dict] = []
    status: dict[str, str] = {}

    for entry in companies:
        if isinstance(entry, str):
            entry = {"company": entry}
        company = entry.get("company")
        if not company:
            status["smartrecruiters:?"] = "error: no company id"
            continue

        try:
            data = get(
                SMARTRECRUITERS.format(company=company),
                params={"limit": 100, "offset": 0},
            ).json()
        except Exception as exc:  # noqa: BLE001
            status[f"smartrecruiters:{company}"] = f"error: {exc}"
            log.info("smartrecruiters %s unavailable (%s)", company, exc)
            continue

        postings = data.get("content") or []
        for p in postings:
            loc = p.get("location") or {}
            city = loc.get("city") or ""
            country = loc.get("country") or ""
            ref = p.get("ref") or ""
            uuid = p.get("id") or ""
            results.append(
                job(
                    source=f"SmartRecruiters:{company}",
                    title=p.get("name") or "",
                    org=entry.get("org") or _pretty(company),
                    url=p.get("applyUrl")
                    or (f"https://jobs.smartrecruiters.com/{company}/{uuid}" if uuid else ref),
                    countries=[country] if country else [],
                    city=city,
                    posted=parse_date(p.get("releasedDate") or p.get("createdOn")),
                    summary=", ".join(x for x in [city, country, loc.get("region") or ""] if x),
                    contract=(p.get("typeOfEmployment") or {}).get("label", ""),
                    extra={"assume_health": bool(entry.get("assume_health"))},
                )
            )
        status[f"smartrecruiters:{company}"] = f"ok: {len(postings)} postings"

    return results, status


def fetch_bamboohr(accounts: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """BambooHR's public careers JSON. Used by IDinsight, among others.

    Shape: {"result":[{"id","jobOpeningName","location":{"city","state","country"},
    "department","employmentStatusLabel",...}]}. Location keys vary between
    installations, so every read is defensive.
    """
    results: list[dict] = []
    status: dict[str, str] = {}

    for entry in accounts:
        if isinstance(entry, str):
            entry = {"sub": entry}
        sub = entry.get("sub")
        if not sub:
            status["bamboohr:?"] = "error: no subdomain"
            continue

        try:
            data = get(BAMBOOHR.format(sub=sub)).json()
        except Exception as exc:  # noqa: BLE001
            status[f"bamboohr:{sub}"] = f"error: {exc}"
            log.info("bamboohr %s unavailable (%s)", sub, exc)
            continue

        rows = data.get("result") if isinstance(data, dict) else data
        rows = rows or []
        for r in rows:
            loc = r.get("location") or {}
            if isinstance(loc, str):
                countries, city = _split_location(loc)
            else:
                city = loc.get("city") or ""
                countries = [loc.get("country")] if loc.get("country") else []
            jid = r.get("id") or r.get("jobOpeningId") or ""
            bits = [
                r.get("department") or "",
                r.get("employmentStatusLabel") or "",
                city,
                " ".join(str(c) for c in countries),
            ]
            results.append(
                job(
                    source=f"BambooHR:{sub}",
                    title=r.get("jobOpeningName") or r.get("title") or "",
                    org=entry.get("org") or _pretty(sub),
                    url=r.get("jobOpeningShareUrl")
                    or f"https://{sub}.bamboohr.com/careers/{jid}",
                    countries=[str(c) for c in countries if c],
                    city=city,
                    posted=parse_date(r.get("datePosted") or r.get("originalOpenDate")),
                    summary=", ".join(b for b in bits if b),
                    contract=r.get("employmentStatusLabel") or "",
                    extra={"assume_health": bool(entry.get("assume_health"))},
                )
            )
        status[f"bamboohr:{sub}"] = f"ok: {len(rows)} postings"

    return results, status


def fetch_workable(accounts: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Workable's public widget JSON. Used by Evidence Action, VillageReach.

    Shape: {"name","jobs":[{"title","shortcode","url","location":{"city",
    "country"},"description"?,"published_on"}]}. details=true asks for the
    description, which the relevance gate wants.
    """
    results: list[dict] = []
    status: dict[str, str] = {}

    for entry in accounts:
        if isinstance(entry, str):
            entry = {"account": entry}
        account = entry.get("account")
        if not account:
            status["workable:?"] = "error: no account"
            continue

        try:
            data = get(WORKABLE.format(account=account)).json()
        except Exception as exc:  # noqa: BLE001
            status[f"workable:{account}"] = f"error: {exc}"
            log.info("workable %s unavailable (%s)", account, exc)
            continue

        jobs = data.get("jobs") or []
        org = entry.get("org") or data.get("name") or _pretty(account)
        for j in jobs:
            loc = j.get("location") or {}
            city = loc.get("city") or ""
            country = loc.get("country") or loc.get("countryCode") or ""
            body = strip_html(j.get("description") or "")
            code = j.get("shortcode") or ""
            results.append(
                job(
                    source=f"Workable:{account}",
                    title=j.get("title") or "",
                    org=org,
                    url=j.get("url")
                    or (f"https://apply.workable.com/{account}/j/{code}/" if code else ""),
                    countries=[country] if country else [],
                    city=city,
                    posted=parse_date(j.get("published_on") or j.get("created_at")),
                    summary=body or ", ".join(x for x in [city, country] if x),
                    contract=j.get("employment_type") or "",
                    extra={
                        "_body": truncate(body, 6000),
                        "assume_health": bool(entry.get("assume_health")),
                    },
                )
            )
        status[f"workable:{account}"] = f"ok: {len(jobs)} postings"

    return results, status
