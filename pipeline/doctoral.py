"""What separates a doctoral route worth applying to from one that is not.

The jobs board asks one question of a listing: is this public health work. The
doctoral track has to ask three more, because the August 2026 scan found that
the binding constraint on this profile was never academic merit.

    1. Is the money actually there?  A PhD advert and a fully funded PhD post
       are different objects. Half of what the word "PhD" returns is a fees-only
       award or an invitation to bring your own scholarship.

    2. Does it require an employer back home?  Three of the six funded routes
       found in August (ITM Antwerp sandwich, Ghent BOF, the TDR fellowship at
       UGM) are built for candidates embedded in a home institute that grants
       study leave and supplies a co-supervisor. Someone between posts is
       ineligible on day one, whatever their CV says.

    3. Is it open to this passport?  "Domestic applicants only", "Home fee
       status" and "Commonwealth citizens" each close a route completely, and
       none of them appear in the title.

Everything here is keyword matching over the listing text, in the same spirit as
pipeline/classify.py: no model, no API key, and every verdict carries the phrase
that produced it, so a wrong call is a one-line edit to config/phd.yaml rather
than a mystery.

TWO RULES THIS MODULE FOLLOWS

Absence of evidence is not evidence of absence. A listing that says nothing
about money is "unstated", never "unfunded". Sweden and the Netherlands rarely
mention funding because a doctoral position there IS an employment contract, and
a classifier that read that silence as "no funding" would delete the best part
of the board. That is what `assume_funding` on a source is for.

Nothing is ever dropped for failing these tests. The page filters; the pipeline
labels. A route you were told about and rejected is worth more than one you were
never shown.
"""
from __future__ import annotations

import re

# Order matters: the first bucket to match wins, and the vetoes come first.
FUNDING_ORDER = ["unfunded", "partial", "salaried", "stipend"]

FUNDING_LABELS = {
    "salaried": "Salaried post",
    "stipend": "Stipend and fees",
    "partial": "Partial or unclear",
    "unfunded": "Not funded",
    "unstated": "Funding not stated",
}

ROUTE_LABELS = {
    "post": "Advertised position",
    "programme": "Programme or scholarship call",
    "fellowship": "Fellowship",
}

PROGRAMME_PATTERNS = [
    r"\bscholarship (scheme|programme|program|call|competition)\b",
    r"\bcall for (applications|candidates|proposals)\b",
    r"\bdoctoral (programme|program|school|college|training partnership)\b",
    r"\bgraduate school\b",
    r"\badmissions? (round|cycle|deadline)\b",
    r"\bapplication round\b",
]

FELLOWSHIP_PATTERNS = [
    r"\bfellowship\b",
    r"\bfellow (scheme|programme|program)\b",
]

# A doctoral route says so in its own title.
DOCTORAL_TITLE = [
    r"\bphd\b",
    r"\bph\.d\b",
    r"\bdoctoral\b",
    r"\bdoctorate\b",
    r"\bdoktorand",
    r"\bpromovendus\b",
    r"\bstudentship\b",
    r"early ?stage researcher",
    r"\bdc\d{1,2}\b",
]

# Titles that are emphatically not a doctoral vacancy, however often the advert
# says "doctoral" further down.
#
# This exists because of a real miss. A Karolinska professorship whose duties
# included "supervise doctoral students" was categorised phd by the jobs board's
# own classifier, which reads the first 1200 characters of the body. On the jobs
# board that is a wrong tab; on a page whose entire purpose is doctoral routes it
# is a wrong page. Professorships, postdocs and research fellowships all mention
# doctoral supervision as a matter of course.
NOT_DOCTORAL_TITLE = [
    r"\bprofessor\b",
    # \w* on purpose, so the whole word is removed when the title is stripped
    # below. With the old r"\bpost[- ]?doc" the veto matched "post-doctoral" but
    # left the string "toral" behind, and "post-doctoral" ALSO satisfied
    # \bdoctoral\b, because the hyphen is a word boundary. The two cancelled out
    # and "Post-doctoral fellow in Biology" was published as a doctoral route.
    r"\bpost[- ]?doc\w*",
    r"\bdoctoral (supervisor|supervision|school committee)\b",
    r"\blecturer\b",
    r"\breader in\b",
    r"\bhead of\b",
    r"\bdirector\b",
    r"\bdean\b",
    r"\btechnician\b",
    r"\bsupervisor\b",
    r"\bresearch (fellow|associate|assistant|officer|scientist|nurse)\b",
    r"\bsenior (scientist|researcher|lecturer)\b",
    r"\bamanuens",
]


def _text(rec: dict) -> str:
    return " ".join(
        str(rec.get(k) or "")
        for k in ("title", "org", "summary", "_body", "contract")
    ).lower()


def _hits(text: str, terms) -> list[str]:
    """Which of these phrases appear, in the order given."""
    found = []
    for term in terms or []:
        t = str(term).lower().strip()
        if t and t in text:
            found.append(t)
    return found


def _any(patterns, text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def is_doctoral(rec: dict, extra_patterns=None) -> bool:
    """Category "phd" plus the programme calls that never say the word.

    classify.categorise already tags anything matching PHD_PATTERNS. This adds
    the scholarship and fellowship calls that fund doctoral study without ever
    calling themselves a PhD vacancy, and it looks at the whole text rather than
    the first 1200 characters, because a funding call buries the word "doctoral"
    deep in the eligibility section.
    """
    title = (rec.get("title") or "").lower()

    # The title has the final say in both directions. A professorship that
    # supervises doctoral students is not a doctoral route; a post that calls
    # itself a PhD position is, whatever else the body says.
    #
    # The vetoed words are CUT OUT of the title before the positive test runs,
    # rather than tested alongside it. Otherwise a word that contains its own
    # contradiction wins both ways: "post-doctoral" matched the veto and then
    # matched \bdoctoral\b in the same breath, and the post was published.
    remainder = title
    for pattern in NOT_DOCTORAL_TITLE:
        remainder = re.sub(pattern, " ", remainder, flags=re.I)

    if remainder != title and not _any(DOCTORAL_TITLE, remainder):
        return False
    if _any(DOCTORAL_TITLE, remainder):
        return True
    if rec.get("category") == "phd":
        return True

    text = _text(rec)
    if not re.search(r"\b(phd|ph\.d|doctoral|doctorate|doktorand|promovendus)\b", text, re.I):
        return False
    return _any(PROGRAMME_PATTERNS + FELLOWSHIP_PATTERNS + (extra_patterns or []), text)


def route_for(rec: dict) -> str:
    text = _text(rec)
    if _any(PROGRAMME_PATTERNS, text):
        return "programme"
    if _any(FELLOWSHIP_PATTERNS, text):
        return "fellowship"
    return "post"


def funding_for(rec: dict, cfg: dict) -> tuple[str, list[str]]:
    """Return (bucket, the phrases that decided it).

    The vetoes run first on purpose. A listing that says "fully funded for home
    students, self-funded applicants also welcome" is not a funded route for
    this profile, and reading it as one is the expensive mistake.
    """
    text = _text(rec)
    banks = cfg.get("funding_terms") or {}

    unfunded = _hits(text, banks.get("unfunded"))
    salaried = _hits(text, banks.get("salaried"))
    stipend = _hits(text, banks.get("stipend"))

    if unfunded and not (salaried or stipend):
        return "unfunded", unfunded
    if unfunded and (salaried or stipend):
        # Both readings present. Say so rather than picking one; the evidence
        # list is there for exactly this case.
        return "partial", unfunded + salaried[:2] + stipend[:2]
    if salaried:
        return "salaried", salaried
    if stipend:
        return "stipend", stipend

    assumed = (rec.get("assume_funding") or "").strip().lower()
    if assumed in FUNDING_LABELS:
        return assumed, ["assumed from the source, not stated in the listing"]
    return "unstated", []


def affiliation_for(rec: dict, cfg: dict) -> tuple[bool, list[str]]:
    hits = _hits(_text(rec), (cfg.get("affiliation_terms") or []))
    return bool(hits), hits


def nationality_for(rec: dict, cfg: dict) -> tuple[bool, list[str]]:
    hits = _hits(_text(rec), (cfg.get("nationality_terms") or []))
    return bool(hits), hits


def enrich(rec: dict, cfg: dict) -> dict:
    """Attach the doctoral fields. Same contract as classify.enrich: mutates."""
    funding, funding_why = funding_for(rec, cfg)
    affiliation, affiliation_why = affiliation_for(rec, cfg)
    nationality, nationality_why = nationality_for(rec, cfg)

    rec["funding"] = funding
    rec["funding_label"] = FUNDING_LABELS[funding]
    rec["funding_evidence"] = funding_why[:4]
    rec["fully_funded"] = funding in {"salaried", "stipend"}
    rec["affiliation_required"] = affiliation
    rec["affiliation_evidence"] = affiliation_why[:4]
    rec["nationality_restricted"] = nationality
    rec["nationality_evidence"] = nationality_why[:4]
    rec["route"] = route_for(rec)
    rec["route_label"] = ROUTE_LABELS[rec["route"]]

    # One number the page can sort on, so "show me what I can actually apply to"
    # is a sort and not a mental exercise. It sits beside the relevance score
    # rather than replacing it: relevance says whether the work fits, this says
    # whether the door is open.
    open_score = 0
    if rec["fully_funded"]:
        open_score += 40
    elif funding == "unstated":
        open_score += 15
    if not affiliation:
        open_score += 25
    if not nationality:
        open_score += 20
    if rec.get("deadline"):
        open_score += 5
    rec["openness"] = open_score
    rec.pop("assume_funding", None)
    return rec


# ---------------------------------------------------------------------------
# The pinned panel, read from the PhD Board sheet instead of the YAML
#
# The YAML version of this panel went a month without an edit and started
# showing closed deadlines as live and a declined supervisor as an open lead. A
# hand-kept list only stays true while somebody keeps it, and the PhD Board
# sheet is already being kept. So the sheet can drive the panel directly: in
# Google Sheets, File, Share, Publish to web, pick the tab, choose
# comma-separated values, and put the URL in config/phd.yaml under
# pipeline_source. Any failure falls back to the YAML rather than emptying the
# panel.
# ---------------------------------------------------------------------------

STATUS_SYNONYMS = {
    "action": ("to apply", "drafting", "draft", "in progress", "preparing", "action",
               "to contact", "to email", "todo", "to do", "next"),
    "sent": ("applied", "submitted", "sent", "emailed", "contacted", "awaiting",
             "waiting", "under review", "interview"),
    "watching": ("watching", "monitoring", "not open", "upcoming", "shortlist",
                 "shortlisted", "identified", "researching", "blocked", "on hold"),
    "closed": ("closed", "rejected", "declined", "withdrawn", "unsuccessful",
               "ineligible", "lapsed", "expired", "done"),
}

# Order matters, and it is the same precedence funding_for uses: the vetoes run
# first. "self-funded only" contains the word "funded", so a stipend-first pass
# reads it as funded, which is the one mistake this field exists to prevent.
FUNDING_SYNONYMS = {
    "unfunded": ("self-fund", "self fund", "unfunded", "no funding", "none"),
    "partial": ("partial", "fees only", "fee waiver", "tuition only", "not guaranteed"),
    "salaried": ("salary", "salaried", "employment", "employed", "contract"),
    "stipend": ("stipend", "scholarship", "fully funded", "fully-funded", "studentship",
                "fellowship", "funded", "bursary", "grant"),
}

DEFAULT_COLUMN_MAP = {
    "name": ["study field", "position", "project", "title"],
    "institution": ["university/institute", "university", "institute", "institution"],
    "department": ["department/research group", "department"],
    "country": ["country"],
    "supervisor": ["supervisor/pi", "supervisor", "pi"],
    "deadline": ["closing date", "deadline"],
    "status": ["status"],
    "funding": ["funding", "funder/scholarship"],
    "route": ["position type"],
    "next_action": ["next action"],
    "notes": ["remarks", "gaps/eligibility concerns"],
    "url": ["link", "url"],
}


def _map_value(raw: str, synonyms: dict, default: str) -> str:
    low = str(raw or "").strip().lower()
    if not low:
        return default
    if low in synonyms:
        return low
    for canonical, words in synonyms.items():
        if any(w in low for w in words):
            return canonical
    return default


def pipeline_from_rows(rows: list[dict], column_map: dict | None = None) -> list[dict]:
    """Turn PhD Board rows into panel entries. Pure, so it is testable offline."""
    cmap = {**DEFAULT_COLUMN_MAP, **(column_map or {})}
    out: list[dict] = []

    for i, row in enumerate(rows):
        lower = {str(k).strip().lower(): (v or "") for k, v in row.items() if k}

        def pick(field: str) -> str:
            for candidate in cmap.get(field, []):
                value = lower.get(str(candidate).strip().lower())
                if value and str(value).strip():
                    return str(value).strip()
            return ""

        name = pick("name")
        institution = pick("institution")
        if not name and not institution:
            continue                      # a blank template row
        department = pick("department")
        if department and department.lower() not in name.lower():
            name = f"{name}, {department}" if name else department

        status = _map_value(pick("status"), STATUS_SYNONYMS, "watching")
        funding = _map_value(pick("funding"), FUNDING_SYNONYMS, "unstated")
        deadline = _parse_sheet_date(pick("deadline"))

        out.append({
            "id": f"board-{i}",
            "name": name or institution,
            "institution": institution,
            "country": pick("country"),
            "supervisor": pick("supervisor"),
            "route": "post",
            "funding": funding,
            "deadline": deadline,
            # A date typed into your own sheet is a date you put there, so it is
            # confirmed when present and "none" when the cell is empty. Nothing
            # from the sheet is ever labelled inferred.
            "date_confidence": "confirmed" if deadline else "none",
            "status": status,
            "affiliation": False,
            "next_action": pick("next_action"),
            "notes": pick("notes"),
            "url": pick("url"),
            "from_board": True,
        })
    return out


def _parse_sheet_date(value: str) -> str:
    from fetch.common import parse_date
    return parse_date(value) or ""


def pipeline_from_csv(url: str, column_map: dict | None = None) -> tuple[list[dict], str]:
    """Fetch a published-to-web CSV of the PhD Board. Returns (entries, status)."""
    import csv
    import io

    from fetch.common import get

    try:
        text = get(url).text
    except Exception as exc:  # noqa: BLE001
        return [], f"error: {exc}"

    # A sheet that is not actually published to the web answers with Google's
    # sign-in page, which parses as CSV perfectly happily and yields nonsense.
    if "<html" in text[:400].lower():
        return [], "error: got an HTML page, not CSV. Is the sheet published to the web?"

    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc:  # noqa: BLE001
        return [], f"error: could not parse the CSV ({exc})"

    entries = pipeline_from_rows(rows, column_map)
    if not entries:
        return [], f"error: {len(rows)} rows read, none had a name or an institution"
    return entries, f"ok: {len(entries)} rows from the PhD Board"


def panel_warnings(pinned: list[dict]) -> list[str]:
    """Housekeeping on the pinned panel. Never raises, never blocks anything.

    These are things worth telling someone about, not defects. Keeping that line
    clear matters: an earlier version of this check lived in the test suite as a
    hard assertion, the suite runs before the fetch in CI, and when one panel
    deadline went by the whole board stopped refreshing for six days. Config
    drift is a notice. Broken code is a failure. They do not share a channel.
    """
    from datetime import date

    today = date.today().isoformat()
    out: list[str] = []

    for e in pinned or []:
        name = str(e.get("name") or "")[:60]
        deadline = e.get("deadline") or ""
        if e.get("status") == "action" and deadline and deadline < today:
            out.append(f"{name}: deadline {deadline} has passed but it is still marked 'needs you'")
        elif e.get("status") in {"action", "sent", "watching"} and deadline and deadline < today:
            out.append(f"{name}: deadline {deadline} has passed")
        if deadline and e.get("date_confidence") == "inferred" and deadline < today:
            out.append(f"{name}: the inferred date {deadline} is in the past, so confirm the real one")
        if e.get("status") == "action" and not str(e.get("next_action") or "").strip():
            out.append(f"{name}: marked 'needs you' with no next action written down")

    return out


def pipeline_entries(cfg: dict) -> list[dict]:
    """The hand-kept panel: routes already being worked, from config.

    Deliberately not merged into the fetched listings. These are tracked because
    a decision was made about them, not because a feed mentioned them, and half
    of them have no advert to fetch at all.
    """
    out = []
    for i, item in enumerate(cfg.get("pipeline") or []):
        entry = dict(item)
        entry.setdefault("id", f"pipeline-{i}")
        entry.setdefault("status", "watching")
        entry.setdefault("date_confidence", "confirmed")
        out.append(entry)
    return out
