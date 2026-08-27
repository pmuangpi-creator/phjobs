"""World Bank country income classification, fetched rather than remembered.

The point of this module is that nobody types a country list from memory. The
World Bank publishes the official income groups through a free, key-free API,
they re-classify every July, and a list hand-written today would be quietly
wrong within a year. So: fetch it, cache it in the repo, and fall back to the
cache when the network fails.

    https://api.worldbank.org/v2/country?format=json&per_page=400

The response is a two-element array: [pagination_metadata, [country, ...]].
Each country carries id (ISO3), iso2Code, name, region, incomeLevel and
capitalCity. incomeLevel.id is one of LIC, LMC, UMC, HIC, or NA. Aggregates
(the "Sub-Saharan Africa" style rows) are distinguishable by
incomeLevel.value == "Aggregates" and are dropped.

capitalCity is why this module also does geography. It gives roughly two
hundred authoritative capital-to-country mappings for free, which is how a
posting that says "Kampala" and never says "Uganda" still gets classified.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fetch.common import get

log = logging.getLogger("phjobs.income")

WB_URL = "https://api.worldbank.org/v2/country"

# LMIC = everything the World Bank does not call high income. Low, lower-middle
# and upper-middle. Change this set if you want a stricter definition.
LMIC_GROUPS = {"LIC", "LMC", "UMC"}

GROUP_LABELS = {
    "LIC": "Low income",
    "LMC": "Lower-middle income",
    "UMC": "Upper-middle income",
    "HIC": "High income",
}

# The World Bank uses formal names. Job adverts do not. These are spelling
# synonyms, not classifications -- mapping "Vietnam" to "Viet Nam" cannot get a
# country's income group wrong, it only decides whether we recognise the word.
ALIASES = {
    "vietnam": "viet nam",
    "laos": "lao pdr",
    "lao": "lao pdr",
    "lao people's democratic republic": "lao pdr",
    "burma": "myanmar",
    "drc": "congo, dem. rep.",
    "dr congo": "congo, dem. rep.",
    "democratic republic of the congo": "congo, dem. rep.",
    "democratic republic of congo": "congo, dem. rep.",
    "congo-kinshasa": "congo, dem. rep.",
    "republic of the congo": "congo, rep.",
    "congo-brazzaville": "congo, rep.",
    "egypt": "egypt, arab rep.",
    "iran": "iran, islamic rep.",
    "south korea": "korea, rep.",
    "republic of korea": "korea, rep.",
    "north korea": "korea, dem. people's rep.",
    "syria": "syrian arab republic",
    "yemen": "yemen, rep.",
    "venezuela": "venezuela, rb",
    "russia": "russian federation",
    "kyrgyzstan": "kyrgyz republic",
    "slovakia": "slovak republic",
    "the gambia": "gambia, the",
    "gambia": "gambia, the",
    "bahamas": "bahamas, the",
    "turkey": "turkiye",
    "cape verde": "cabo verde",
    "ivory coast": "cote d'ivoire",
    "côte d'ivoire": "cote d'ivoire",
    "swaziland": "eswatini",
    "macedonia": "north macedonia",
    "east timor": "timor-leste",
    "palestine": "west bank and gaza",
    "occupied palestinian territory": "west bank and gaza",
    "gaza": "west bank and gaza",
    "west bank": "west bank and gaza",
    "tanzania": "tanzania",
    "united republic of tanzania": "tanzania",
    "moldova": "moldova",
    "republic of moldova": "moldova",
    "brunei": "brunei darussalam",
    "micronesia": "micronesia, fed. sts.",
    "st lucia": "st. lucia",
    "saint lucia": "st. lucia",
    "hong kong": "hong kong sar, china",
    "macau": "macao sar, china",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "great britain": "united kingdom",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "wales": "united kingdom",
    "northern ireland": "united kingdom",
    "usa": "united states",
    "u.s.a.": "united states",
    "u.s.": "united states",
    "united states of america": "united states",
    "uae": "united arab emirates",
    "czech republic": "czechia",
    "cape verde islands": "cabo verde",
    "bolivia": "bolivia",
    "plurinational state of bolivia": "bolivia",
}

# Well-known non-capital cities that turn up in health job adverts. Kept short
# and only where the city unambiguously identifies one country. Capitals come
# from the API and are not duplicated here.
EXTRA_CITIES = {
    "mae sot": "thailand",
    "chiang mai": "thailand",
    "yangon": "myanmar",
    "mandalay": "myanmar",
    "cox's bazar": "bangladesh",
    "chattogram": "bangladesh",
    "chittagong": "bangladesh",
    "mumbai": "india",
    "bengaluru": "india",
    "bangalore": "india",
    "chennai": "india",
    "kolkata": "india",
    "hyderabad": "india",
    "pune": "india",
    "karachi": "pakistan",
    "lahore": "pakistan",
    "ho chi minh city": "viet nam",
    "saigon": "viet nam",
    "surabaya": "indonesia",
    "bandung": "indonesia",
    "cebu": "philippines",
    "davao": "philippines",
    "mombasa": "kenya",
    "kisumu": "kenya",
    "kilifi": "kenya",
    "arusha": "tanzania",
    "mwanza": "tanzania",
    "zanzibar": "tanzania",
    "ifakara": "tanzania",
    "bagamoyo": "tanzania",
    "lagos": "nigeria",
    "kano": "nigeria",
    "maiduguri": "nigeria",
    "ibadan": "nigeria",
    "goma": "congo, dem. rep.",
    "bukavu": "congo, dem. rep.",
    "kisangani": "congo, dem. rep.",
    "port sudan": "sudan",
    "nyala": "sudan",
    "el fasher": "sudan",
    "aleppo": "syrian arab republic",
    "erbil": "iraq",
    "mosul": "iraq",
    "basra": "iraq",
    "gaziantep": "turkiye",
    "istanbul": "turkiye",
    "alexandria": "egypt, arab rep.",
    "casablanca": "morocco",
    "durban": "south africa",
    "johannesburg": "south africa",
    "cape town": "south africa",
    "sao paulo": "brazil",
    "são paulo": "brazil",
    "rio de janeiro": "brazil",
    "guadalajara": "mexico",
    "medellin": "colombia",
    "medellín": "colombia",
    "shanghai": "china",
    "guangzhou": "china",
    "geneva": "switzerland",
    "new york": "united states",
    "washington": "united states",
    "boston": "united states",
    "seattle": "united states",
    "atlanta": "united states",
    "london": "united kingdom",
    "oxford": "united kingdom",
    "cambridge": "united kingdom",
    "liverpool": "united kingdom",
    "edinburgh": "united kingdom",
    "glasgow": "united kingdom",
    "manchester": "united kingdom",
    "rotterdam": "netherlands",
    "nijmegen": "netherlands",
    "utrecht": "netherlands",
    "heidelberg": "germany",
    "munich": "germany",
    "hamburg": "germany",
    "barcelona": "spain",
    "antwerp": "belgium",
    "melbourne": "australia",
    "sydney": "australia",
    "brisbane": "australia",
    "perth": "australia",
    "toronto": "canada",
    "montreal": "canada",
    "vancouver": "canada",
}


class Classifier:
    """Maps a country or city name to its World Bank income group."""

    def __init__(self, countries: list[dict]):
        self.countries = countries
        self.by_name: dict[str, dict] = {}
        self.by_code: dict[str, dict] = {}
        self.by_capital: dict[str, dict] = {}

        for c in countries:
            name = (c.get("name") or "").strip()
            if not name:
                continue
            self.by_name[name.lower()] = c
            for code in (c.get("id"), c.get("iso2Code")):
                if code:
                    self.by_code[str(code).strip().lower()] = c
            cap = (c.get("capitalCity") or "").strip().lower()
            if cap:
                self.by_capital[cap] = c

        for city, country_name in EXTRA_CITIES.items():
            hit = self.by_name.get(country_name)
            if hit:
                self.by_capital.setdefault(city, hit)

        # One regex over every recognisable place name, longest first so that
        # "South Sudan" wins over "Sudan" and "Guinea-Bissau" over "Guinea".
        terms = set(self.by_name) | set(self.by_capital) | set(ALIASES)
        terms = {t for t in terms if len(t) > 3}
        self._re = re.compile(
            r"(?<![a-z])(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?![a-z])",
            re.I,
        )

    # -- lookups ---------------------------------------------------------

    def lookup(self, place: str) -> dict | None:
        if not place:
            return None
        key = place.strip().lower().strip(".,;:")
        if key in ALIASES:
            key = ALIASES[key]
        return self.by_name.get(key) or self.by_code.get(key) or self.by_capital.get(key)

    def find_in_text(self, text: str, limit: int = 4) -> list[dict]:
        """Every country a block of text mentions, in order of appearance."""
        out: list[dict] = []
        seen: set[str] = set()
        for match in self._re.finditer(text or ""):
            hit = self.lookup(match.group(1))
            if hit and hit["id"] not in seen:
                seen.add(hit["id"])
                out.append(hit)
            if len(out) >= limit:
                break
        return out

    # -- classification --------------------------------------------------

    def group_for(self, places: list[str]) -> tuple[str, str, list[str]]:
        """Return (income_id, label, canonical_country_names) for a duty station.

        When a posting lists several countries the lowest income group wins:
        a role split between Nairobi and Geneva is field work, not Swiss work.
        """
        order = ["LIC", "LMC", "UMC", "HIC"]
        best: str | None = None
        names: list[str] = []
        seen: set[str] = set()
        for place in places or []:
            hit = self.lookup(place)
            if not hit:
                continue
            # "Nairobi" and "Kenya" both resolve to Kenya; the card should not
            # read "Kenya, Kenya".
            if hit["id"] not in seen:
                seen.add(hit["id"])
                names.append(hit["name"])
            gid = ((hit.get("incomeLevel") or {}).get("id") or "").upper()
            if gid in order and (best is None or order.index(gid) < order.index(best)):
                best = gid
        if best is None:
            return "", "", names
        return best, GROUP_LABELS.get(best, best), names


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def _usable(countries: list[dict]) -> list[dict]:
    """Drop the aggregate rows; keep real economies."""
    out = []
    for c in countries or []:
        level = c.get("incomeLevel") or {}
        if str(level.get("value", "")).strip().lower() == "aggregates":
            continue
        if not c.get("name") or not c.get("id"):
            continue
        out.append(c)
    return out


def load(cache_path: Path, refresh: bool = True) -> tuple[Classifier, str]:
    """Fetch the classification, falling back to the committed cache.

    Returns (classifier, status_string) so the run can report which happened.
    """
    countries: list[dict] = []
    status = ""

    if refresh:
        try:
            payload = get(WB_URL, params={"format": "json", "per_page": 400}).json()
            if isinstance(payload, list) and len(payload) >= 2:
                countries = _usable(payload[1])
            if countries:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(countries, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                status = f"ok: {len(countries)} economies from the World Bank"
                log.info("income classification refreshed: %s economies", len(countries))
        except Exception as exc:  # noqa: BLE001
            log.warning("World Bank fetch failed (%s); falling back to cache", exc)
            status = f"error: {exc}"

    if not countries:
        if cache_path.exists():
            try:
                countries = _usable(json.loads(cache_path.read_text(encoding="utf-8")))
                status = (status or "") + f" | using cache: {len(countries)} economies"
                log.info("income classification loaded from cache: %s", len(countries))
            except Exception as exc:  # noqa: BLE001
                log.error("income cache unreadable: %s", exc)
                status += f" | cache unreadable: {exc}"
        else:
            log.error("no income classification available; LMIC tagging disabled")
            status += " | no cache, LMIC tagging disabled"

    return Classifier(countries), status.strip(" |")
