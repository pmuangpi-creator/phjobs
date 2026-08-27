#!/usr/bin/env python3
"""Fetch every enabled source, filter, score, merge, write docs/data/.

Run locally:      python3 run_refresh.py
Dry run:          python3 run_refresh.py --dry-run
One source only:  python3 run_refresh.py --only reliefweb
Louder:           python3 run_refresh.py -v

Exit code is 0 whenever at least one source produced jobs. A single dead feed is
a normal Tuesday, not a build failure; only a total wipeout fails the run, and
even then the previous data file is left untouched.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from fetch import boards, pagefetch, reliefweb, rssfeeds
from pipeline import classify, income, merge, outputs

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
DATA = ROOT / "docs" / "data"
JOBS_PATH = DATA / "jobs.json"
STATUS_PATH = DATA / "sources_status.json"
ICS_PATH = DATA / "deadlines.ics"
DIGEST_PATH = DATA / "digest.md"
DIGEST_TITLE = DATA / "digest_title.txt"
INCOME_CACHE = CONFIG / "income_groups.json"

log = logging.getLogger("phjobs")


def load_yaml(name: str) -> dict:
    with (CONFIG / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the public health jobs board")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    # No demo mode. It existed so the page could be looked at before the first
    # real fetch, and its fabricated rows then survived that fetch as
    # "unconfirmed" listings. The board has real data now; the generator is gone
    # and merge.load_previous still discards any demo row it finds.
    ap.add_argument(
        "--only",
        default="",
        help="reliefweb | greenhouse | lever | workday | smartrecruiters | rss",
    )
    ap.add_argument(
        "--discover",
        metavar="URL",
        default="",
        help="print the link shapes on a page, to help write a link_pattern",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.discover:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        print(pagefetch.discover(args.discover))
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    started = time.time()
    sources = load_yaml("sources.yaml")
    profile = load_yaml("profile.yaml")
    only = args.only.strip().lower()

    raw: list[dict] = []
    status: dict[str, str] = {}

    # --- ReliefWeb -------------------------------------------------------
    rw = sources.get("reliefweb") or {}
    if rw.get("enabled", True) and only in ("", "reliefweb"):
        try:
            got = reliefweb.fetch(rw)
            raw.extend(got)
            status["reliefweb"] = f"ok: {len(got)} jobs"
        except Exception as exc:  # noqa: BLE001
            status["reliefweb"] = f"error: {exc}"
            log.error("ReliefWeb failed: %s", exc)

    # --- Greenhouse ------------------------------------------------------
    gh = sources.get("greenhouse") or {}
    if gh.get("enabled", True) and only in ("", "greenhouse"):
        got, st = boards.fetch_greenhouse(gh.get("boards") or [])
        raw.extend(got)
        status.update(st)

    # --- Lever -----------------------------------------------------------
    lv = sources.get("lever") or {}
    if lv.get("enabled", True) and only in ("", "lever"):
        got, st = boards.fetch_lever(lv.get("companies") or [])
        raw.extend(got)
        status.update(st)

    # --- Workday ---------------------------------------------------------
    wd = sources.get("workday") or {}
    if wd.get("enabled", True) and only in ("", "workday"):
        got, st = boards.fetch_workday(wd.get("sites") or [])
        raw.extend(got)
        status.update(st)

    # --- SmartRecruiters -------------------------------------------------
    sr = sources.get("smartrecruiters") or {}
    if sr.get("enabled", True) and only in ("", "smartrecruiters"):
        got, st = boards.fetch_smartrecruiters(sr.get("companies") or [])
        raw.extend(got)
        status.update(st)

    # --- BambooHR --------------------------------------------------------
    bh = sources.get("bamboohr") or {}
    if bh.get("enabled", True) and only in ("", "bamboohr"):
        got, st = boards.fetch_bamboohr(bh.get("accounts") or [])
        raw.extend(got)
        status.update(st)

    # --- Workable --------------------------------------------------------
    wk = sources.get("workable") or {}
    if wk.get("enabled", True) and only in ("", "workable"):
        got, st = boards.fetch_workable(wk.get("accounts") or [])
        raw.extend(got)
        status.update(st)

    # --- RSS -------------------------------------------------------------
    rs = sources.get("rss") or {}
    if rs.get("enabled", True) and only in ("", "rss"):
        got, st = rssfeeds.fetch(rs.get("feeds") or [])
        raw.extend(got)
        status.update(st)

    # --- listing pages with no feed --------------------------------------
    pg = sources.get("pages") or {}
    if pg.get("enabled", True) and only in ("", "pages"):
        got, st = pagefetch.harvest(pg.get("sites") or [])
        raw.extend(got)
        status.update(st)

    log.info("fetched %s raw postings from %s source slots", len(raw), len(status))

    if not raw:
        log.error("every source returned nothing. Leaving existing data in place.")
        _write_status(status, {}, started, wrote=False, dry=args.dry_run)
        return 1

    # --- full descriptions -----------------------------------------------
    # Done before the gate, deliberately. A feed gives two lines, and judging
    # relevance, category and LMIC focus on two lines is how listings end up in
    # the wrong bucket. Only postings not seen on an earlier run are fetched.
    previous = merge.load_previous(JOBS_PATH)
    bodies = sources.get("full_descriptions") or {}
    if bodies.get("enabled", True):
        status["full-descriptions"] = pagefetch.add_bodies(
            raw, set(previous), limit=int(bodies.get("max_per_run", 120))
        )

    # --- income classification -------------------------------------------
    # Fetched, never remembered. The World Bank re-classifies every July and a
    # hand-written country list would be quietly wrong within a year.
    classifier, income_status = income.load(INCOME_CACHE, refresh=True)
    status["worldbank-income-groups"] = income_status or "unknown"

    # --- gate, enrich ----------------------------------------------------
    gate_terms = profile.get("health_gate") or []
    exclude_terms = profile.get("exclude_terms") or []
    kept: list[dict] = []
    rejected = 0
    for rec in raw:
        if classify.passes_gate(rec, gate_terms, exclude_terms):
            kept.append(classify.enrich(rec, profile, classifier))
        else:
            rejected += 1
    log.info("relevance gate: kept %s, dropped %s as not public health", len(kept), rejected)

    # --- merge -----------------------------------------------------------
    jobs, stats = merge.merge(
        kept,
        previous,
        expire_after_days=int(sources.get("expire_after_days", 2)),
        stale_after_days=int(sources.get("stale_after_days", 45)),
    )
    stats["gate_rejected"] = rejected

    counts: dict[str, int] = {}
    for j in jobs:
        counts[j["category"]] = counts.get(j["category"], 0) + 1
    log.info("by category: %s", counts)

    lmic_ds = sum(1 for j in jobs if j.get("lmic_duty_station"))
    lmic_fo = sum(1 for j in jobs if j.get("lmic_focus"))
    located = sum(1 for j in jobs if j.get("countries"))
    stats["lmic_duty_station"] = lmic_ds
    stats["lmic_focus"] = lmic_fo
    stats["with_location"] = located
    log.info(
        "LMIC: %s based in an LMIC, %s LMIC-focused | %s/%s have a resolved country",
        lmic_ds, lmic_fo, located, len(jobs),
    )

    if args.dry_run:
        log.info("dry run, nothing written")
        for j in jobs[:15]:
            log.info(
                "  [%3d] %-9s %-55s | %s | %s",
                j["score"], j["category"], j["title"][:55],
                ", ".join(j["countries"])[:28] or "-", j["source"],
            )
        _write_status(status, stats, started, wrote=False, dry=True)
        return 0

    DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(jobs),
        "by_category": counts,
        "stats": stats,
        "jobs": jobs,
    }
    JOBS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info("wrote %s (%s jobs, %.1f KB)", JOBS_PATH, len(jobs), JOBS_PATH.stat().st_size / 1024)

    # --- calendar feed ---------------------------------------------------
    alerts = sources.get("alerts") or {}
    cal = sources.get("calendar") or {}
    if cal.get("enabled", True):
        ICS_PATH.write_text(
            outputs.build_ics(
                jobs,
                min_score=int(cal.get("min_score", 0)),
                horizon_days=int(cal.get("horizon_days", 120)),
            ),
            encoding="utf-8",
        )
        log.info("wrote %s", ICS_PATH)

    # --- digest ----------------------------------------------------------
    # Written to a file rather than sent from here. The workflow decides how it
    # reaches you, which keeps credentials out of this script entirely.
    if alerts.get("enabled", True):
        title, body, n = outputs.build_digest(
            jobs,
            set(previous),
            min_score=int(alerts.get("min_score", 30)),
            closing_days=int(alerts.get("closing_days", 3)),
            site_url=alerts.get("site_url", ""),
        )
        DIGEST_PATH.write_text(body, encoding="utf-8")
        DIGEST_TITLE.write_text(title, encoding="utf-8")
        stats["digest_items"] = n
        log.info("digest: %s items%s", n, "" if n else " (nothing worth sending)")

    _write_status(status, stats, started, wrote=True, dry=False)
    return 0


def _write_status(status, stats, started, *, wrote: bool, dry: bool) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    ok = sum(1 for v in status.values() if str(v).startswith("ok"))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_seconds": round(time.time() - started, 1),
        "sources_ok": ok,
        "sources_total": len(status),
        "wrote_data": wrote,
        "dry_run": dry,
        "stats": stats,
        "sources": dict(sorted(status.items())),
    }
    STATUS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("source health: %s/%s reporting ok -> %s", ok, len(status), STATUS_PATH)


if __name__ == "__main__":
    sys.exit(main())
