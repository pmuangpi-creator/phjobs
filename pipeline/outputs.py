"""Two things the board emits besides the page itself.

A calendar feed, because closing dates are what people actually miss, and a
digest, because a board you have to remember to visit is a board you stop
visiting.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger("phjobs.outputs")


# --------------------------------------------------------------------------
# iCalendar
# --------------------------------------------------------------------------


def _ics_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545 wants lines under 75 octets, continued with a leading space."""
    out, current = [], line
    while len(current.encode("utf-8")) > 73:
        cut = 73
        while cut > 1 and len(current[:cut].encode("utf-8")) > 73:
            cut -= 1
        out.append(current[:cut])
        current = " " + current[cut:]
    out.append(current)
    return "\r\n".join(out)


def build_ics(jobs: list[dict], *, min_score: int = 0, horizon_days: int = 120) -> str:
    """An all-day event on each closing date.

    Subscribe once and every future refresh updates it. Events use a stable UID
    derived from the job id, so a job whose deadline is corrected moves in the
    calendar instead of appearing twice.
    """
    today = date.today()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    horizon = today + timedelta(days=horizon_days)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//phjobs//public health jobs board//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Public health job deadlines",
        "X-WR-CALDESC:Closing dates from the public health jobs board",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    count = 0
    for j in jobs:
        deadline = j.get("deadline")
        if not deadline or int(j.get("score") or 0) < min_score:
            continue
        try:
            d = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < today or d > horizon:
            continue

        uid = hashlib.sha1(f"phjobs-{j.get('id')}".encode()).hexdigest()[:20]
        where = ", ".join(j.get("countries") or []) or "Location not stated"
        if j.get("city"):
            where = f"{j['city']}, {where}"
        tags = []
        if j.get("lmic_duty_station"):
            tags.append("LMIC based")
        if j.get("lmic_focus"):
            tags.append("LMIC focus")

        desc = " | ".join(
            filter(None, [
                j.get("org", ""),
                where,
                f"relevance {j.get('score', 0)}",
                ", ".join(tags),
                j.get("url", ""),
            ])
        )

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@phjobs",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            _fold("SUMMARY:Closes: " + _ics_escape(j.get("title", ""))),
            _fold("DESCRIPTION:" + _ics_escape(desc)),
            _fold("LOCATION:" + _ics_escape(where)),
            _fold("URL:" + _ics_escape(j.get("url", ""))),
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "TRIGGER:-P3D",
            "ACTION:DISPLAY",
            _fold("DESCRIPTION:Closes in 3 days: " + _ics_escape(j.get("title", ""))),
            "END:VALARM",
            "END:VEVENT",
        ]
        count += 1

    lines.append("END:VCALENDAR")
    log.info("calendar: %s deadlines", count)
    return "\r\n".join(lines) + "\r\n"


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------


def _row(j: dict, site_url: str = "") -> str:
    where = ", ".join(j.get("countries") or []) or "location not stated"
    tags = []
    if j.get("lmic_duty_station"):
        tags.append("LMIC")
    if j.get("lmic_focus"):
        tags.append("focus")
    tag = f" `{'/'.join(tags)}`" if tags else ""
    close = f" · closes {j['deadline']}" if j.get("deadline") else ""
    return (
        f"- **[{j.get('title', 'Untitled')}]({j.get('url', '')})** "
        f"({j.get('score', 0)}){tag}  \n"
        f"  {j.get('org', 'Organisation not stated')} · {where}{close} · "
        f"{j.get('source', '')}"
    )


def build_digest(
    jobs: list[dict],
    previous_ids: set[str],
    *,
    min_score: int = 30,
    closing_days: int = 3,
    site_url: str = "",
) -> tuple[str, str, int]:
    """Return (title, markdown_body, item_count).

    Two sections that answer different questions: what is new that I would
    want, and what am I about to run out of time on. Returns a count of zero
    when there is nothing worth sending, so the workflow can stay quiet.
    """
    today = date.today()

    fresh = [
        j for j in jobs
        if j.get("id") not in previous_ids
        and int(j.get("score") or 0) >= min_score
        and not j.get("stale")
    ]
    fresh.sort(key=lambda j: -int(j.get("score") or 0))

    closing = []
    for j in jobs:
        if not j.get("deadline"):
            continue
        try:
            d = datetime.strptime(j["deadline"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (d - today).days <= closing_days and int(j.get("score") or 0) >= min_score:
            closing.append((d, j))
    closing.sort(key=lambda pair: (pair[0], -int(pair[1].get("score") or 0)))

    if not fresh and not closing:
        return "", "", 0

    parts = []
    if fresh:
        parts.append(f"### {len(fresh)} new, scoring {min_score} or above\n")
        parts += [_row(j) for j in fresh[:25]]
        if len(fresh) > 25:
            parts.append(f"\n_and {len(fresh) - 25} more on the board._")
        parts.append("")

    if closing:
        word = "day" if closing_days == 1 else f"{closing_days} days"
        parts.append(f"### Closing within {word}\n")
        parts += [_row(j) for _, j in closing]
        parts.append("")

    lmic_n = sum(1 for j in fresh if j.get("lmic_duty_station") or j.get("lmic_focus"))
    parts.append("---")
    parts.append(
        f"{len(jobs)} open positions on the board, {lmic_n} of the new ones LMIC-related."
    )
    if site_url:
        parts.append(f"\n[Open the board]({site_url})")
    parts.append(
        "\n_Tune what reaches you here in `config/profile.yaml`. "
        "Close this issue and the next digest opens a fresh one._"
    )

    bits = []
    if fresh:
        bits.append(f"{len(fresh)} new")
    if closing:
        bits.append(f"{len(closing)} closing soon")
    title = f"Jobs digest {today.isoformat()}: " + ", ".join(bits)

    # Distinct jobs, not rows. A listing that is both new and closing soon
    # appears in both sections, and counting it twice would overstate the
    # digest in the run stats.
    distinct = {j.get("id") for j in fresh} | {j.get("id") for _, j in closing}
    return title, "\n".join(parts), len(distinct)
