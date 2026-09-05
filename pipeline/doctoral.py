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
    r"\bpost[- ]?doc",
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
    if _any(NOT_DOCTORAL_TITLE, title) and not _any(DOCTORAL_TITLE, title):
        return False
    if _any(DOCTORAL_TITLE, title):
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
