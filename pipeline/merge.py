"""Deduplication, expiry, and carrying first_seen across runs.

first_seen is the reason this file exists. Without persistence, every run looks
like the first run and "new since Tuesday" is meaningless. The previous
docs/data/jobs.json is read back at the start of a run, matched by id, and the
original first_seen date wins.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("phjobs.merge")

_NORM = re.compile(r"[^a-z0-9]+")


def _fingerprint(rec: dict) -> str:
    """Cross-source duplicate key.

    The same vacancy often appears on ReliefWeb and on the employer's own
    Greenhouse board. Title plus organisation, aggressively normalised, catches
    most of those without merging genuinely distinct posts that share a title
    across different employers.
    """
    title = _NORM.sub(" ", (rec.get("title") or "").lower()).strip()
    org = _NORM.sub(" ", (rec.get("org") or "").lower()).strip()
    country = _NORM.sub(" ", " ".join(rec.get("countries") or []).lower()).strip()
    return f"{title}|{org}|{country}"


# Preferred source when the same vacancy shows up twice. Employer boards link
# straight to the application form, so they win over the aggregator.
SOURCE_RANK = [
    "Greenhouse:",
    "Lever:",
    "ReliefWeb",
    "RSS:",
]


def _rank(rec: dict) -> int:
    src = rec.get("source", "")
    for i, prefix in enumerate(SOURCE_RANK):
        if src.startswith(prefix):
            return i
    return len(SOURCE_RANK)


def load_previous(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read previous data (%s); starting fresh", exc)
        return {}
    jobs = payload.get("jobs") if isinstance(payload, dict) else payload

    # Fabricated placeholder rows must never survive into a real run. Without
    # this, the carry-forward rule below treats them as postings a source had a
    # bad day on and keeps them alive for 45 days, which is exactly what
    # happened on the first live fetch.
    kept, dropped = {}, 0
    for j in jobs or []:
        if not j.get("id"):
            continue
        if j.get("demo"):
            dropped += 1
            continue
        kept[j["id"]] = j
    if dropped:
        log.info("discarded %s demo rows from the previous data file", dropped)
    return kept


def _is_expired(rec: dict, grace_days: int) -> bool:
    deadline = rec.get("deadline")
    if not deadline:
        return False
    try:
        d = datetime.strptime(deadline, "%Y-%m-%d").date()
    except ValueError:
        return False
    return d < date.today() - timedelta(days=grace_days)


def _is_too_old(rec: dict, max_age_days: int) -> bool:
    """For postings with no closing date: how long since it was published?

    Falls back to when we first saw it, for sources that give no posting date
    either. Without this, a vacancy with no deadline never leaves the board.
    """
    when = rec.get("posted") or rec.get("first_seen")
    if not when:
        return False
    try:
        d = datetime.strptime(when, "%Y-%m-%d").date()
    except ValueError:
        return False
    return d < date.today() - timedelta(days=max_age_days)


def merge(
    fresh: list[dict],
    previous: dict[str, dict],
    *,
    expire_after_days: int = 0,
    stale_after_days: int = 7,
    healthy_sources: set[str] | None = None,
    max_age_days: int = 0,
) -> tuple[list[dict], dict]:
    today = datetime.now(timezone.utc).date().isoformat()
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=stale_after_days)).isoformat()
    healthy = {s.lower() for s in (healthy_sources or set())}

    by_id: dict[str, dict] = {}

    # 1. this run's results, best source per id
    for rec in fresh:
        rid = rec.get("id")
        if not rid or not rec.get("title") or not rec.get("url"):
            continue
        existing = by_id.get(rid)
        if existing is None or _rank(rec) < _rank(existing):
            by_id[rid] = rec

    # 2. carry first_seen forward
    for rid, rec in by_id.items():
        old = previous.get(rid)
        rec["first_seen"] = (old or {}).get("first_seen") or rec.get("posted") or today
        rec["last_seen"] = today

    # 3. carry forward ONLY what a broken source would otherwise have taken with
    #    it.
    #
    #    This used to keep every unseen job for 45 days, which is why closed
    #    vacancies lingered on the board. The reasoning was sound and the rule
    #    was too blunt: carry-forward exists so that one source having a bad
    #    afternoon does not empty the board, not so that a job stays visible
    #    after the employer took it down. If a source answered normally this run
    #    and did not return a job it returned last time, the job is gone. Drop
    #    it. Only jobs whose source actually failed get the grace period.
    revived = dropped_gone = 0
    for rid, old in previous.items():
        if rid in by_id:
            continue
        src = str(old.get("source") or "").lower()
        if src in healthy:
            dropped_gone += 1          # source is fine, the listing is not
            continue
        last_seen = old.get("last_seen") or old.get("first_seen") or ""
        if last_seen >= cutoff:
            old["stale"] = True
            by_id[rid] = old
            revived += 1

    # 4. drop anything closed, and anything too old to trust.
    #    A posting with no closing date is the awkward case: nothing marks it as
    #    finished, so it sits there indefinitely. max_age_days retires those on
    #    their posting date instead.
    live = []
    dropped_expired = dropped_old = 0
    for r in by_id.values():
        if _is_expired(r, expire_after_days):
            dropped_expired += 1
            continue
        if max_age_days and not r.get("deadline") and _is_too_old(r, max_age_days):
            dropped_old += 1
            continue
        live.append(r)

    # 5. collapse cross-source duplicates
    best_by_fp: dict[str, dict] = {}
    for rec in live:
        fp = _fingerprint(rec)
        current = best_by_fp.get(fp)
        if current is None or _rank(rec) < _rank(current):
            if current is not None:
                rec.setdefault("also_on", []).append(current.get("source"))
                rec["first_seen"] = min(
                    filter(None, [rec.get("first_seen"), current.get("first_seen")]),
                    default=rec.get("first_seen"),
                )
            best_by_fp[fp] = rec
        else:
            current.setdefault("also_on", [])
            if rec.get("source") not in current["also_on"]:
                current["also_on"].append(rec.get("source"))

    deduped = list(best_by_fp.values())
    deduped.sort(
        key=lambda r: (-int(r.get("score") or 0), r.get("deadline") or "9999-12-31")
    )

    stats = {
        "fetched": len(fresh),
        "unique_ids": len(by_id),
        "carried_over": revived,
        "delisted_by_source": dropped_gone,
        "expired_dropped": dropped_expired,
        "aged_out_no_deadline": dropped_old,
        "duplicates_collapsed": len(live) - len(deduped),
        "published": len(deduped),
    }
    log.info("merge: %s", stats)
    return deduped, stats
