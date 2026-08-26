"""Shared plumbing for every source adapter.

One job record, one shape. Adapters are responsible for producing that shape and
for nothing else; relevance, category and scoring all happen later in the
pipeline so that a change of judgement never means touching a fetcher.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import time
from datetime import datetime, timezone

import requests
from dateutil import parser as dateparser

log = logging.getLogger("phjobs")

USER_AGENT = (
    "phjobs-aggregator/1.0 (public health job aggregator; "
    "contact via the GitHub repository)"
)
TIMEOUT = 40
RETRIES = 3

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, application/rss+xml, text/xml, */*",
                "Accept-Language": "en",
            }
        )
        _session = s
    return _session


def _request(method: str, url: str, **kwargs) -> requests.Response:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            r = session().request(method, url, timeout=TIMEOUT, **kwargs)
            if r.status_code in (429, 502, 503, 504):
                wait = 4 * (attempt + 1)
                log.warning("%s %s -> %s, backing off %ss", method, url, r.status_code, wait)
                time.sleep(wait)
                last = requests.HTTPError(f"{r.status_code} from {url}")
                continue
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001 - adapters must never crash a run
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
    raise last if last else RuntimeError(f"request to {url} failed")


def get(url: str, **kwargs) -> requests.Response:
    return _request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return _request("POST", url, **kwargs)


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


def truncate(text: str, limit: int = 900) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" .,;:-") + "..."


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------


def parse_date(value) -> str | None:
    """Best-effort date parse. Returns YYYY-MM-DD, or None if unparseable.

    Accepts ISO strings, RFC 822 feed dates, unix timestamps in seconds or
    milliseconds, and time.struct_time as feedparser hands it over.
    """
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        if isinstance(value, time.struct_time):
            return datetime(*value[:6], tzinfo=timezone.utc).date().isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()
        dt = dateparser.parse(str(value), fuzzy=True)
        if dt is None:
            return None
        return dt.date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------

_ID_STRIP = re.compile(r"[?#].*$")


def make_id(source: str, url: str, title: str = "") -> str:
    """Stable id across runs. URL-based so the same posting keeps its first_seen.

    Query strings and fragments are dropped because several boards append
    tracking parameters that change between fetches.
    """
    base = _ID_STRIP.sub("", (url or "").strip().lower()) or f"{source}:{title}".lower()
    return hashlib.sha1(f"{source}|{base}".encode("utf-8")).hexdigest()[:16]


def job(
    *,
    source: str,
    title: str,
    url: str,
    org: str = "",
    countries=None,
    city: str = "",
    posted: str | None = None,
    deadline: str | None = None,
    summary: str = "",
    contract: str = "",
    seniority: str = "",
    hint_category: str = "",
    extra: dict | None = None,
) -> dict:
    """Build a normalised record. Adapters should call only this."""
    title = (title or "").strip()
    url = (url or "").strip()
    countries = [c.strip() for c in (countries or []) if c and c.strip()]
    rec = {
        "id": make_id(source, url, title),
        "source": source,
        "title": title,
        "org": (org or "").strip(),
        "url": url,
        "countries": countries,
        "city": (city or "").strip(),
        "posted": posted,
        "deadline": deadline,
        "summary": truncate(summary),
        "contract": (contract or "").strip(),
        "seniority": (seniority or "").strip(),
        "hint_category": hint_category or "",
    }
    if extra:
        rec.update(extra)
    return rec
