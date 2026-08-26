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

from fetch import boards, reliefweb, rssfeeds
from pipeline import classify, merge

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
DATA = ROOT / "docs" / "data"
JOBS_PATH = DATA / "jobs.json"
STATUS_PATH = DATA / "sources_status.json"

log = logging.getLogger("phjobs")


def load_yaml(name: str) -> dict:
    with (CONFIG / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the public health jobs board")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    ap.add_argument("--only", default="", help="reliefweb | greenhouse | lever | rss")
    ap.add_argument(
        "--demo",
        action="store_true",
        help="write six fabricated postings so the page can be viewed offline",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

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

    if args.demo:
        from pipeline import demo

        raw = demo.samples()
        status["demo"] = f"ok: {len(raw)} fabricated postings"
        log.warning("DEMO MODE: writing invented postings, not real vacancies")
        only = "__demo__"

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

    # --- RSS -------------------------------------------------------------
    rs = sources.get("rss") or {}
    if rs.get("enabled", True) and only in ("", "rss"):
        got, st = rssfeeds.fetch(rs.get("feeds") or [])
        raw.extend(got)
        status.update(st)

    log.info("fetched %s raw postings from %s source slots", len(raw), len(status))

    if not raw:
        log.error("every source returned nothing. Leaving existing data in place.")
        _write_status(status, {}, started, wrote=False, dry=args.dry_run)
        return 1

    # --- gate, enrich ----------------------------------------------------
    gate_terms = profile.get("health_gate") or []
    kept: list[dict] = []
    rejected = 0
    for rec in raw:
        if classify.passes_gate(rec, gate_terms):
            kept.append(classify.enrich(rec, profile))
        else:
            rejected += 1
    log.info("relevance gate: kept %s, dropped %s as not public health", len(kept), rejected)

    # --- merge -----------------------------------------------------------
    # Demo mode starts from nothing so fabricated rows never mix with real ones.
    previous = {} if args.demo else merge.load_previous(JOBS_PATH)
    jobs, stats = merge.merge(
        kept,
        previous,
        expire_after_days=int(sources.get("expire_after_days", 2)),
        stale_after_days=int(sources.get("stale_after_days", 45)),
    )
    stats["gate_rejected"] = rejected

    counts = {}
    for j in jobs:
        counts[j["category"]] = counts.get(j["category"], 0) + 1
    log.info("by category: %s", counts)

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
        "demo": bool(args.demo),
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
