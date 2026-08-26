"""Relevance gate, category assignment, theme tagging and scoring.

Everything here is keyword matching over lowercased text. No model, no API key,
no per-run cost, and every decision is inspectable: if a job you wanted got
dropped, add the word that would have caught it to config/profile.yaml and the
next run picks it up.

The gate and the score do different jobs and should not be confused. The gate is
a yes/no on "is this public health work", and it is deliberately generous,
because a board with a few irrelevant rows is a nuisance while a board that
silently swallows the job you wanted is worthless. The score only sorts.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# category patterns, evaluated in order -- first match wins
# ---------------------------------------------------------------------------

PHD_PATTERNS = [
    r"\bphd\b",
    r"\bph\.d\b",
    r"doctoral (candidate|researcher|student|position|fellow)",
    r"\bdoctorate\b",
    r"\bstudentship\b",
    r"early ?stage researcher",
    r"\bpromovendus\b",
    r"doctoral training",
    r"\bdc\d{1,2}\b",  # Marie Curie doctoral candidate slots
]

RESEARCH_PATTERNS = [
    r"research (assistant|associate|fellow|officer|coordinator|scientist|manager|analyst)",
    r"\bpost[- ]?doc",
    r"\bpostdoctoral\b",
    r"\bepidemiologist\b",
    r"\bbiostatistician\b",
    r"\b(data|statistical) (analyst|scientist)\b",
    r"\bstudy coordinator\b",
    r"\btrial (coordinator|manager)\b",
    r"\bscientific officer\b",
    r"\blecturer\b",
    r"\bassistant professor\b",
    r"\bsenior scientist\b",
    r"\bresearcher\b",
]

UN_ORG_PATTERNS = [
    r"\bwho\b",
    r"world health organization",
    r"\bunicef\b",
    r"\bunfpa\b",
    r"\bundp\b",
    r"\bunops\b",
    r"\bunhcr\b",
    r"\bunaids\b",
    r"\bunodc\b",
    r"\bunesco\b",
    r"\bunrwa\b",
    r"\bun women\b",
    r"\bunv\b",
    r"united nations",
    r"\biom\b",
    r"international organization for migration",
    r"\bwfp\b",
    r"world food programme",
    r"\bfao\b",
    r"\bilo\b",
    r"\bwoah\b",
    r"world organisation for animal health",
    r"world bank",
    r"\bgavi\b",
    r"global fund",
    r"\bunitaid\b",
    r"\bpaho\b",
    r"\bafdb\b",
    r"asian development bank",
]

GOV_PATTERNS = [
    r"ministry of health",
    r"department of health",
    r"public health england",
    r"health security agency",
    r"\bcdc\b",
    r"centers for disease control",
    r"\becdc\b",
    r"\bnhs\b",
    r"national institute",
    r"\bmoh\b",
    r"health authority",
]

SENIORITY_PATTERNS = [
    (r"\b(director|head of|chief|country representative)\b", "Director / Head"),
    (r"\b(senior|lead|principal|coordinator|manager|specialist|advisor|adviser)\b", "Senior / Manager"),
    (r"\b(officer|associate|analyst|consultant)\b", "Mid"),
    (r"\b(assistant|junior|graduate|trainee|fellow|candidate)\b", "Entry / Junior"),
    (r"\b(intern|internship|volunteer)\b", "Intern / Volunteer"),
]

REMOTE_PATTERNS = [
    r"\bremote\b",
    r"\bhome[- ]based\b",
    r"\bwork from home\b",
    r"\bfully distributed\b",
    r"\bteleworking\b",
]

# ---------------------------------------------------------------------------
# geography
# ---------------------------------------------------------------------------

REGIONS = {
    "South-East Asia": [
        "myanmar", "burma", "thailand", "cambodia", "lao", "viet nam", "vietnam",
        "indonesia", "philippines", "malaysia", "singapore", "timor-leste",
        "brunei",
    ],
    "South Asia": [
        "bangladesh", "india", "nepal", "pakistan", "sri lanka", "bhutan",
        "maldives", "afghanistan",
    ],
    "East Asia & Pacific": [
        "china", "japan", "korea", "mongolia", "papua new guinea", "fiji",
        "solomon islands", "vanuatu", "samoa", "tonga", "australia",
        "new zealand", "hong kong", "taiwan",
    ],
    "Europe": [
        "united kingdom", "england", "scotland", "wales", "ireland", "netherlands",
        "germany", "france", "belgium", "switzerland", "austria", "sweden",
        "norway", "denmark", "finland", "iceland", "spain", "portugal", "italy",
        "greece", "poland", "czech", "hungary", "romania", "bulgaria", "croatia",
        "serbia", "slovenia", "slovakia", "estonia", "latvia", "lithuania",
        "luxembourg", "malta", "cyprus", "ukraine", "moldova", "albania",
    ],
    "Middle East & North Africa": [
        "egypt", "libya", "tunisia", "algeria", "morocco", "sudan", "syria",
        "lebanon", "jordan", "iraq", "iran", "yemen", "palestin", "israel",
        "saudi", "united arab emirates", "qatar", "kuwait", "oman", "bahrain",
        "turkey", "turkiye",
    ],
    "Sub-Saharan Africa": [
        "nigeria", "kenya", "ethiopia", "uganda", "tanzania", "rwanda", "burundi",
        "somalia", "south sudan", "drc", "democratic republic of the congo",
        "congo", "ghana", "senegal", "mali", "niger", "chad", "cameroon",
        "burkina", "cote d'ivoire", "côte d'ivoire", "ivory coast", "liberia",
        "sierra leone", "guinea", "benin", "togo", "gambia", "zambia", "zimbabwe",
        "malawi", "mozambique", "angola", "namibia", "botswana", "south africa",
        "lesotho", "eswatini", "madagascar", "central african republic",
        "eritrea", "djibouti", "mauritania", "gabon",
    ],
    "Americas": [
        "united states", "usa", "canada", "mexico", "brazil", "argentina",
        "chile", "colombia", "peru", "bolivia", "ecuador", "venezuela",
        "guatemala", "honduras", "el salvador", "nicaragua", "costa rica",
        "panama", "haiti", "dominican republic", "jamaica", "cuba", "guyana",
    ],
    "Central Asia & Caucasus": [
        "kazakhstan", "uzbekistan", "kyrgyz", "tajikistan", "turkmenistan",
        "georgia", "armenia", "azerbaijan", "russia", "belarus",
    ],
}

# Countries we try to spot in free text when a source gives us no location field.
_ALL_COUNTRIES = sorted(
    {c for names in REGIONS.values() for c in names}, key=len, reverse=True
)
_COUNTRY_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _ALL_COUNTRIES) + r")\b", re.I
)


def region_for(countries: list[str]) -> str:
    for country in countries:
        low = country.lower()
        for region, members in REGIONS.items():
            if any(m in low for m in members):
                return region
    return "Unspecified"


def guess_countries(text: str, limit: int = 3) -> list[str]:
    found: list[str] = []
    for match in _COUNTRY_RE.finditer(text or ""):
        name = match.group(1).title()
        if name not in found:
            found.append(name)
        if len(found) >= limit:
            break
    return found


# ---------------------------------------------------------------------------


def _haystack(rec: dict) -> str:
    parts = [
        rec.get("title", ""),
        rec.get("org", ""),
        rec.get("summary", ""),
        rec.get("_body", "") or "",
        " ".join(rec.get("countries") or []),
        rec.get("city", "") or "",
        " ".join(rec.get("rw_categories") or []),
        " ".join(rec.get("rw_themes") or []),
    ]
    return (" ".join(str(p) for p in parts)).lower()


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def passes_gate(rec: dict, gate_terms: list[str]) -> bool:
    # Some sources hand over a title and a city and nothing else. When the
    # employer is itself a health organisation, judging its whole board on the
    # title alone throws away real vacancies, so the config can waive the gate
    # per source. The negative weights still sink the finance and IT roles.
    if rec.get("assume_health"):
        return True

    text = _haystack(rec)
    # ReliefWeb's own taxonomy is a strong positive signal on its own.
    for tag in (rec.get("rw_themes") or []) + (rec.get("rw_categories") or []):
        low = str(tag).lower()
        if "health" in low or "nutrition" in low or "water sanitation" in low:
            return True
    return any(term.lower() in text for term in gate_terms)


def categorise(rec: dict) -> str:
    title = (rec.get("title") or "").lower()
    org = (rec.get("org") or "").lower()
    text = _haystack(rec)

    if _any(PHD_PATTERNS, title) or _any(PHD_PATTERNS, text[:1200]):
        return "phd"
    if _any(RESEARCH_PATTERNS, title):
        return "research"
    if _any(UN_ORG_PATTERNS, org):
        return "un"
    if _any(GOV_PATTERNS, org):
        return "gov"
    if rec.get("hint_category"):
        return rec["hint_category"]
    if _any(RESEARCH_PATTERNS, text[:1500]):
        return "research"
    if rec.get("source", "").startswith(("ReliefWeb", "Greenhouse", "Lever")):
        return "ngo"
    return "other"


def seniority_for(rec: dict) -> str:
    existing = (rec.get("seniority") or "").strip()
    if existing:
        return existing
    title = (rec.get("title") or "").lower()
    for pattern, label in SENIORITY_PATTERNS:
        if re.search(pattern, title, re.I):
            return label
    return ""


# The profile file stores match stems, which make poor labels. "epidemiolog"
# has to stay a stem so it catches epidemiologist and epidemiological, but
# nobody wants to read it on a card.
THEME_LABELS = {
    "epidemiolog": "Epidemiology",
    "biostatistic": "Biostatistics",
    "low- and middle-income": "LMIC",
    "lmic": "LMIC",
    "non-communicable": "NCD",
    "noncommunicable": "NCD",
    "ncd": "NCD",
    "tb": "TB",
    "hiv": "HIV",
    "m&e": "M&E",
    "monitoring and evaluation": "M&E",
    "conflict-affected": "Conflict-affected",
    "community health worker": "CHW",
    "systematic review": "Systematic review",
    "one health": "One Health",
}

# When both are present, the second adds nothing over the first.
THEME_SUBSUMES = {
    "Active case finding": "Case finding",
    "Implementation research": "Implementation science",
}


def themes_for(rec: dict, theme_weights: dict) -> list[str]:
    text = _haystack(rec)
    labels: set[str] = set()
    for term in theme_weights:
        raw = str(term).lower()
        # Match on the term exactly as written, spaces included -- " tb " is
        # padded on purpose so it does not fire inside Westbourne.
        if not raw.strip() or raw not in text:
            continue
        clean = raw.strip().strip('"')
        label = THEME_LABELS.get(clean)
        if label is None:
            label = clean.upper() if len(clean) <= 3 else clean.capitalize()
        labels.add(label)

    for keeper, dropped in THEME_SUBSUMES.items():
        if keeper in labels:
            labels.discard(dropped)

    return sorted(labels)[:7]


def score_for(rec: dict, profile: dict, category: str) -> int:
    text = _haystack(rec)
    title = (rec.get("title") or "").lower()
    score = 0

    for term, weight in (profile.get("theme_weights") or {}).items():
        if str(term).lower() in text:
            score += int(weight)

    country_text = " ".join(rec.get("countries") or []).lower() + " " + (rec.get("city") or "").lower()
    for term, weight in (profile.get("country_weights") or {}).items():
        term = str(term).lower()
        if term in country_text or (term in text and len(term) > 6):
            score += int(weight)

    score += int((profile.get("category_weights") or {}).get(category, 0))

    for term, weight in (profile.get("negative_weights") or {}).items():
        if str(term).lower() in title:
            score += int(weight)

    # Nudge fresh postings up so a stale high-scorer does not sit on top forever.
    return max(score, 0)


def language_flags_for(rec: dict, flags: list[str]) -> list[str]:
    text = _haystack(rec)
    return [f for f in (flags or []) if str(f).lower() in text]


def enrich(rec: dict, profile: dict) -> dict:
    """Attach every derived field. Returns the same dict, mutated."""
    category = categorise(rec)
    countries = rec.get("countries") or []
    if not countries:
        countries = guess_countries(
            (rec.get("title") or "") + " " + (rec.get("summary") or "")
        )
        rec["countries"] = countries

    rec["category"] = category
    rec["region"] = region_for(countries)
    rec["seniority"] = seniority_for(rec)
    rec["themes"] = themes_for(rec, profile.get("theme_weights") or {})
    rec["score"] = score_for(rec, profile, category)
    rec["remote"] = _any(REMOTE_PATTERNS, _haystack(rec))
    rec["language_flags"] = language_flags_for(rec, profile.get("language_flags") or [])
    # Source-specific scratch fields have done their work by now; keeping them
    # would roughly double the size of jobs.json for no benefit to the page.
    for key in ("_body", "hint_category", "rw_categories", "rw_themes", "assume_health"):
        rec.pop(key, None)
    return rec
