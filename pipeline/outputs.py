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


def pipeline_as_jobs(pinned: list[dict]) -> list[dict]:
    """The hand-kept doctoral panel, in job shape, so it can share the calendar.

    A deadline you set yourself is the one most worth an alarm, and it would be
    perverse for the calendar to carry a Swedish vacancy nobody has decided
    about while leaving the DAAD date off. Entries already finished, and those
    with no published date, are skipped.
    """
    out = []
    for entry in pinned or []:
        if entry.get("status") == "closed" or not entry.get("deadline"):
            continue
        confidence = entry.get("date_confidence") or "confirmed"
        title = entry.get("name", "")
        if confidence != "confirmed":
            title = f"{title} ({confidence} date, confirm it)"
        out.append({
            "id": entry.get("id"),
            "title": title,
            "org": entry.get("institution", ""),
            "url": entry.get("url", ""),
            "countries": [entry["country"]] if entry.get("country") else [],
            "city": "",
            "deadline": entry.get("deadline"),
            "score": 100,
        })
    return out


def build_ics(
    jobs: list[dict],
    *,
    min_score: int = 0,
    horizon_days: int = 120,
    calendar_name: str = "Public health job deadlines",
    calendar_desc: str = "Closing dates from the public health jobs board",
) -> str:
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
        f"X-WR-CALNAME:{calendar_name}",
        f"X-WR-CALDESC:{calendar_desc}",
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


def _doctoral_row(r: dict) -> str:
    bits = [r.get("funding_label", "")]
    if r.get("affiliation_required"):
        bits.append("needs a home employer")
    if r.get("nationality_restricted"):
        bits.append("check eligibility")
    close = f" · closes {r['deadline']}" if r.get("deadline") else ""
    where = ", ".join(r.get("countries") or []) or "location not stated"
    return (
        f"- **[{r.get('title', 'Untitled')}]({r.get('url', '')})**  \n"
        f"  {r.get('org') or 'Institution not stated'} · {where}{close} · "
        f"{' · '.join(b for b in bits if b)}"
    )


def _pinned_row(entry: dict, days: int) -> str:
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    confidence = entry.get("date_confidence") or "confirmed"
    caveat = "" if confidence == "confirmed" else f" _({confidence} date)_"
    action = (entry.get("next_action") or "").strip()
    return (
        f"- **{entry.get('name', '')}** — {entry.get('institution', '')}, "
        f"closes {entry.get('deadline')} ({when}){caveat}"
        + (f"  \n  {action}" if action else "")
    )


def build_digest(
    jobs: list[dict],
    previous_ids: set[str],
    *,
    min_score: int = 30,
    closing_days: int = 3,
    site_url: str = "",
    doctoral: list[dict] | None = None,
    pinned: list[dict] | None = None,
    doctoral_closing_days: int = 21,
) -> tuple[str, str, int]:
    """Return (title, markdown_body, item_count).

    Sections that answer different questions: what is new that I would want,
    what am I about to run out of time on, and what has moved on the doctoral
    side. Returns a count of zero when there is nothing worth sending, so the
    workflow can stay quiet.

    Doctoral deadlines get a three-week warning rather than three days, because
    a supervisor confirmation letter is not something you produce on a Thursday
    evening.
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

    # -- doctoral track ----------------------------------------------------
    new_phd = [
        r for r in (doctoral or [])
        if r.get("id") not in previous_ids and r.get("fully_funded") and not r.get("stale")
    ]
    new_phd.sort(key=lambda r: (-int(r.get("openness") or 0), -int(r.get("score") or 0)))

    phd_closing = []
    for r in doctoral or []:
        if not r.get("deadline") or not r.get("fully_funded"):
            continue
        try:
            d = datetime.strptime(r["deadline"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (d - today).days <= doctoral_closing_days:
            phd_closing.append((d, r))
    phd_closing.sort(key=lambda pair: pair[0])

    pinned_due = []
    for entry in pinned or []:
        if entry.get("status") == "closed" or not entry.get("deadline"):
            continue
        try:
            d = datetime.strptime(entry["deadline"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if 0 <= (d - today).days <= doctoral_closing_days:
            pinned_due.append((d, entry))
    pinned_due.sort(key=lambda pair: pair[0])

    if not fresh and not closing and not new_phd and not phd_closing and not pinned_due:
        return "", "", 0

    parts = []

    # Your own deadlines first. Nothing a feed turned up outranks a date you
    # already decided to work towards.
    if pinned_due:
        parts.append(f"### Your doctoral pipeline, next {doctoral_closing_days} days\n")
        parts += [_pinned_row(e, (d - today).days) for d, e in pinned_due]
        parts.append("")

    if new_phd:
        parts.append(f"### {len(new_phd)} new fully funded doctoral route" +
                     ("s" if len(new_phd) != 1 else "") + "\n")
        parts += [_doctoral_row(r) for r in new_phd[:12]]
        if len(new_phd) > 12:
            parts.append(f"\n_and {len(new_phd) - 12} more on the doctoral page._")
        parts.append("")

    if phd_closing:
        parts.append(f"### Funded doctoral routes closing within {doctoral_closing_days} days\n")
        parts += [_doctoral_row(r) for _, r in phd_closing[:12]]
        parts.append("")

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
    funded_n = sum(1 for r in (doctoral or []) if r.get("fully_funded"))
    parts.append("---")
    parts.append(
        f"{len(jobs)} open positions on the board, {lmic_n} of the new ones "
        f"LMIC-related. {funded_n} fully funded doctoral routes on the PhD page."
    )
    if site_url:
        parts.append(f"\n[Open the board]({site_url}) · [Doctoral routes]({site_url.rstrip('/')}/phd.html)")
    parts.append(
        "\n_Tune what reaches you here in `config/profile.yaml`. "
        "Close this issue and the next digest opens a fresh one._"
    )

    bits = []
    if pinned_due:
        bits.append(f"{len(pinned_due)} of your PhD deadlines")
    if fresh:
        bits.append(f"{len(fresh)} new")
    if closing:
        bits.append(f"{len(closing)} closing soon")
    if new_phd:
        bits.append(f"{len(new_phd)} funded PhD")
    if phd_closing and not pinned_due:
        bits.append(f"{len(phd_closing)} PhD closing")
    title = f"Jobs digest {today.isoformat()}: " + ", ".join(bits)

    # Distinct items, not rows. A listing that is both new and closing soon
    # appears in both sections, and counting it twice would overstate the
    # digest in the run stats.
    distinct = (
        {j.get("id") for j in fresh}
        | {j.get("id") for _, j in closing}
        | {r.get("id") for r in new_phd}
        | {r.get("id") for _, r in phd_closing}
        | {e.get("id") for _, e in pinned_due}
    )
    return title, "\n".join(parts), len(distinct)
