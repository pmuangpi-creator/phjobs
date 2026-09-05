#!/usr/bin/env python3
"""Offline checks for the doctoral track.

Runs without a network. Every fixture below is a shape that was actually seen
in the wild or a mistake the classifier could plausibly make, and the point of
each check is stated in its name so a failure reads as a sentence.

    python3 tests_doctoral.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from fetch import sitemaps
from pipeline import classify, doctoral, outputs

ROOT = Path(__file__).resolve().parent
PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))


def d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


CFG = yaml.safe_load((ROOT / "config" / "phd.yaml").read_text(encoding="utf-8"))
PIPE = yaml.safe_load((ROOT / "config" / "phd_pipeline.yaml").read_text(encoding="utf-8"))
PROFILE = yaml.safe_load((ROOT / "config" / "profile.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# sitemap parsing
# ---------------------------------------------------------------------------

VARBI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ki.varbi.com/en/what:job/jobID:123/</loc>
    <lastmod>2026-09-01</lastmod>
    <meta_title>Doctoral (PhD) student in global health, tuberculosis epidemiology</meta_title>
    <meta_city>Stockholm</meta_city>
    <meta_country>Sweden</meta_country>
    <meta_ends>2026-10-15</meta_ends>
    <meta_customer_fullname>Karolinska Institutet</meta_customer_fullname>
    <meta_type>Doctoral student</meta_type>
    <meta_description>The doctoral position concerns tuberculosis surveillance in
      conflict-affected settings and is placed at the Department of Global Public
      Health.</meta_description>
  </url>
  <url>
    <loc>https://ki.varbi.com/en/what:job/jobID:124/</loc>
    <meta_title>Professor of Haematology</meta_title>
    <meta_city>Solna</meta_city>
    <meta_country>Sweden</meta_country>
  </url>
</urlset>
"""

PLAIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.academictransfer.com/en/jobs/359291/phd-position-in-global-health-implementation-research/</loc></url>
  <url><loc>https://www.academictransfer.com/nl/jobs/359292/promovendus-mondzorg/</loc></url>
  <url><loc>https://www.academictransfer.com/en/jobs/359293/assistant-professor-of-natural-language-processing/</loc></url>
  <url><loc>https://www.academictransfer.com/en/jobs/359294/</loc></url>
</urlset>
"""

INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.org/sitemap-vacancies.xml</loc></sitemap>
</sitemapindex>
"""


def test_sitemaps() -> None:
    print("\nsitemap parsing")

    varbi = sitemaps._varbi_records(
        ET.fromstring(VARBI_XML),
        {"name": "Varbi KI", "country": "Sweden", "assume_funding": "salaried"},
    )
    check("a rich sitemap yields one record per url", len(varbi) == 2, str(len(varbi)))
    first = varbi[0]
    check("meta_title becomes the title", first["title"].startswith("Doctoral (PhD) student"))
    check("meta_ends becomes the closing date", first["deadline"] == "2026-10-15", str(first["deadline"]))
    check("meta_city becomes the duty station", first["city"] == "Stockholm")
    check("meta_customer_fullname becomes the organisation",
          first["org"] == "Karolinska Institutet", first["org"])
    check("assume_funding rides along on the record",
          first["assume_funding"] == "salaried")
    check("a short description asks for the full page",
          first["_needs_body"] is True)

    spec = {
        "name": "AcademicTransfer",
        "country": "Netherlands",
        "include_pattern": "/en/jobs/.*(phd|promovendus|doctoral|doctorate)",
        "exclude_pattern": "/nl/jobs/",
        "max_items": 50,
        "assume_funding": "salaried",
    }
    plain = sitemaps._plain_records(ET.fromstring(PLAIN_XML), spec)
    urls = [r["url"] for r in plain]
    check("the include pattern keeps the PhD url", any("359291" in u for u in urls))
    check("the exclude pattern drops the Dutch duplicate", not any("/nl/" in u for u in urls))
    check("a non-doctoral vacancy is filtered out", not any("359293" in u for u in urls))
    check("a url with no slug is skipped rather than titled with its id",
          not any("359294" in u for u in urls))
    check("the title is read out of the slug",
          plain[0]["title"].lower().startswith("phd position in global health"),
          plain[0]["title"])

    got, status = sitemaps.harvest([{"name": "off", "url": "https://x", "enabled": False}])
    check("a disabled sitemap is reported, not fetched",
          got == [] and status["sitemap:off"] == "disabled")

    root = ET.fromstring(INDEX_XML)
    check("a sitemap index is a recognisable mistake, not a crash",
          sitemaps._tag(root) == "sitemapindex")


# ---------------------------------------------------------------------------
# funding, affiliation, nationality
# ---------------------------------------------------------------------------

def rec(title: str, body: str = "", **kw) -> dict:
    base = {"title": title, "org": kw.pop("org", "Some University"),
            "summary": body[:400], "_body": body, "url": "https://example.org/x",
            "id": kw.pop("id", title[:20]), "category": "phd", "countries": []}
    base.update(kw)
    return base


def test_funding() -> None:
    print("\nfunding")

    salaried = doctoral.enrich(rec(
        "PhD candidate in health systems",
        "You will be employed for four years. The gross monthly salary ranges from "
        "EUR 2,901 to EUR 3,707 in accordance with the collective labour agreement.",
    ), CFG)
    check("an employment contract reads as salaried", salaried["funding"] == "salaried",
          salaried["funding"])
    check("salaried counts as fully funded", salaried["fully_funded"] is True)
    check("the deciding phrase is recorded", bool(salaried["funding_evidence"]))

    stipend = doctoral.enrich(rec(
        "Funded PhD studentship in TB epidemiology",
        "This fully funded studentship covers tuition fees and provides a tax-free "
        "stipend at the UKRI rate for three and a half years.",
    ), CFG)
    check("a studentship reads as stipend", stipend["funding"] == "stipend", stipend["funding"])
    check("stipend counts as fully funded", stipend["fully_funded"] is True)

    unfunded = doctoral.enrich(rec(
        "PhD opportunity in maternal health",
        "This is a self-funded project. Applicants must secure their own funding "
        "before registration.",
    ), CFG)
    check("a self-funded project reads as unfunded", unfunded["funding"] == "unfunded",
          unfunded["funding"])
    check("unfunded is not fully funded", unfunded["fully_funded"] is False)

    mixed = doctoral.enrich(rec(
        "PhD in global health",
        "A fully funded studentship with a stipend is available to home students. "
        "Self-funded international applicants are also welcome to apply.",
    ), CFG)
    check("funded and self-funded in the same advert reads as partial, not funded",
          mixed["funding"] == "partial", mixed["funding"])
    check("partial is not counted as fully funded", mixed["fully_funded"] is False)

    silent = doctoral.enrich(rec(
        "PhD position in epidemiology",
        "We are looking for a candidate with a master's degree in epidemiology.",
    ), CFG)
    check("silence about money is 'unstated', never 'unfunded'",
          silent["funding"] == "unstated", silent["funding"])
    check("unstated is not counted as fully funded", silent["fully_funded"] is False)

    assumed = doctoral.enrich(rec(
        "PhD position in epidemiology",
        "We are looking for a candidate with a master's degree in epidemiology.",
        assume_funding="salaried",
    ), CFG)
    check("a source known to be salaried rescues a silent advert",
          assumed["funding"] == "salaried" and assumed["fully_funded"] is True)
    check("the assumption is labelled as an assumption",
          "assumed" in " ".join(assumed["funding_evidence"]))
    check("assume_funding is stripped before publication",
          "assume_funding" not in assumed)


def test_eligibility() -> None:
    print("\neligibility")

    sandwich = doctoral.enrich(rec(
        "Individual sandwich PhD scholarship",
        "Candidates must be employed by a home institution which grants study leave "
        "and provides a local co-supervisor for the duration of the programme.",
    ), CFG)
    check("a sandwich scheme is flagged as needing a home employer",
          sandwich["affiliation_required"] is True)
    check("the phrase behind the flag is recorded",
          bool(sandwich["affiliation_evidence"]))

    open_post = doctoral.enrich(rec(
        "PhD candidate, implementation research",
        "Applications are open to candidates worldwide. A master's degree in public "
        "health is required. Gross monthly salary per the collective agreement.",
    ), CFG)
    check("an open post carries no home-employer flag",
          open_post["affiliation_required"] is False)

    restricted = doctoral.enrich(rec(
        "PhD scholarship in population health",
        "This award is open to domestic applicants only. International students are "
        "not eligible for this round.",
    ), CFG)
    check("a domestic-only award is flagged", restricted["nationality_restricted"] is True)

    check("openness ranks an open funded route above a restricted one",
          open_post["openness"] > restricted["openness"],
          f"{open_post['openness']} vs {restricted['openness']}")
    check("openness ranks a funded route above a sandwich one",
          open_post["openness"] > sandwich["openness"])


def test_detection() -> None:
    print("\nwhat counts as doctoral")

    check("anything the jobs board already tagged phd is doctoral",
          doctoral.is_doctoral({"category": "phd", "title": "PhD candidate"}) is True)

    call = {
        "category": "other",
        "title": "DAAD Research Grants",
        "summary": "A call for applications for doctoral study in Germany, funding "
                   "from October 2027.",
        "_body": "",
    }
    check("a funding call that never says 'vacancy' is still doctoral",
          doctoral.is_doctoral(call, CFG.get("extra_doctoral_patterns")) is True)

    postdoc = {
        "category": "research",
        "title": "Postdoctoral researcher in epidemiology",
        "summary": "Applicants must hold a PhD in epidemiology or a related field.",
        "_body": "",
    }
    check("a postdoc asking for a PhD is not a doctoral route",
          doctoral.is_doctoral(postdoc, CFG.get("extra_doctoral_patterns")) is False)

    professor = {
        "category": "phd",   # the jobs board's own classifier gets this wrong
        "title": "Professor of Haematology",
        "summary": "The professor will supervise doctoral students.",
        "_body": "",
    }
    check("a professorship that supervises doctoral students is not a doctoral route",
          doctoral.is_doctoral(professor, CFG.get("extra_doctoral_patterns")) is False)

    both = {
        "category": "other",
        "title": "Research Fellow (PhD studentship in TB epidemiology)",
        "summary": "", "_body": "",
    }
    check("a title carrying both readings is kept, not discarded",
          doctoral.is_doctoral(both, CFG.get("extra_doctoral_patterns")) is True)

    check("a scholarship call is routed as a programme",
          doctoral.route_for({"title": "Hong Kong PhD Fellowship Scheme",
                              "summary": "call for applications", "_body": ""})
          in {"programme", "fellowship"})


# ---------------------------------------------------------------------------
# pinned pipeline, calendar, digest
# ---------------------------------------------------------------------------

def test_pipeline() -> None:
    print("\npinned pipeline")

    entries = doctoral.pipeline_entries(PIPE)
    check("the pipeline file loads", len(entries) >= 10, str(len(entries)))
    check("every entry has an id", all(e.get("id") for e in entries))
    check("every entry has a status the page knows",
          all(e["status"] in {"action", "sent", "watching", "closed"} for e in entries),
          str(sorted({e["status"] for e in entries})))
    check("every dated entry says how confident that date is",
          all(e.get("date_confidence") in {"confirmed", "inferred", "none"} for e in entries))
    check("an inferred date is never presented as confirmed",
          all(e["date_confidence"] != "confirmed" or e.get("deadline") != ""
              for e in entries if e.get("date_confidence") == "inferred"))

    as_jobs = outputs.pipeline_as_jobs(entries)
    check("finished entries stay out of the calendar",
          not any("Radboudumc" in (j.get("org") or "") for j in as_jobs))
    check("entries with no published date stay out of the calendar",
          all(j.get("deadline") for j in as_jobs))
    check("an inferred date is labelled in the calendar entry itself",
          any("inferred" in j["title"] for j in as_jobs))


def test_outputs() -> None:
    print("\ncalendar and digest")

    routes = [
        doctoral.enrich(rec("PhD candidate in TB epidemiology",
                            "Gross monthly salary per the collective labour agreement.",
                            id="r1", deadline=d(9), score=60, first_seen=d(0),
                            countries=["Sweden"], source="Sitemap:Varbi KI"), CFG),
        doctoral.enrich(rec("Self-funded PhD in nutrition",
                            "Applicants must secure their own funding.",
                            id="r2", deadline=d(12), score=20, first_seen=d(0),
                            countries=["United Kingdom"], source="RSS:Leeds"), CFG),
    ]

    ics = outputs.build_ics(routes, horizon_days=300, calendar_name="Doctoral deadlines")
    check("the calendar is named for the doctoral track",
          "X-WR-CALNAME:Doctoral deadlines" in ics)
    check("both dated routes get an event", ics.count("BEGIN:VEVENT") == 2)

    pinned = [{"id": "p1", "name": "DAAD", "institution": "DAAD",
               "deadline": d(10), "date_confidence": "confirmed", "status": "action",
               "next_action": "Get the supervisor letter.", "country": "Germany"}]

    title, body, n = outputs.build_digest(
        [], set(), doctoral=routes, pinned=pinned, doctoral_closing_days=21,
        site_url="https://example.org/phjobs/",
    )
    check("a digest fires on doctoral news even with no job news", n > 0, str(n))
    check("your own deadline leads the digest", body.strip().startswith("### Your doctoral pipeline"))
    check("the next action travels with it", "Get the supervisor letter." in body)
    check("the funded route is announced", "PhD candidate in TB epidemiology" in body)
    check("the self-funded one is not", "Self-funded PhD in nutrition" not in body)
    check("the doctoral page is linked", "phd.html" in body)
    check("the title says what moved", "PhD" in title, title)

    quiet_title, quiet_body, quiet_n = outputs.build_digest([], set(), doctoral=[], pinned=[])
    check("nothing to say means nothing is sent", quiet_n == 0 and quiet_body == "")


def test_end_to_end() -> None:
    """The whole doctoral half of a run, on fixtures, writing a real phd.json."""
    print("\nend to end, offline")

    raw = sitemaps._varbi_records(
        ET.fromstring(VARBI_XML),
        {"name": "Varbi KI", "country": "Sweden", "assume_funding": "salaried"},
    ) + sitemaps._plain_records(
        ET.fromstring(PLAIN_XML),
        {"name": "AcademicTransfer", "country": "Netherlands",
         "include_pattern": "/en/jobs/.*(phd|doctoral)", "exclude_pattern": "/nl/jobs/",
         "assume_funding": "salaried"},
    )
    # Stand in for pagefetch.add_bodies, which is the step that gives a listing
    # enough text to judge. Each fixture gets the body its real page would have.
    BODIES = {
        "Sitemap:AcademicTransfer": (
            "PhD position in global health implementation research. Four-year "
            "employment contract, gross monthly salary per the CAO Nederlandse "
            "Universiteiten."
        ),
        "Professor of Haematology": (
            "The professor will lead the haematology research group and supervise "
            "doctoral students. Specialist physician certification is required."
        ),
    }
    for r in raw:
        if r.get("summary"):
            continue
        body = BODIES.get(r["title"]) or BODIES.get(r["source"], "")
        r["summary"] = r["_body"] = body

    gate = [r for r in raw
            if classify.passes_gate(r, PROFILE["health_gate"], PROFILE["exclude_terms"])]
    check("the health gate keeps the global health doctoral posts", len(gate) >= 2, str(len(gate)))

    enriched = [classify.enrich(r, PROFILE) for r in gate]
    routes = [doctoral.enrich(r, CFG)
              for r in enriched
              if doctoral.is_doctoral(r, CFG.get("extra_doctoral_patterns"))]
    check("both doctoral posts survive the whole chain", len(routes) == 2, str(len(routes)))
    check("the haematology professor does not reach the doctoral page",
          not any("Haematology" in r["title"] for r in routes),
          "; ".join(r["title"] for r in routes))
    check("both are fully funded", all(r["fully_funded"] for r in routes))

    payload = {
        "generated_at": "2026-09-05T00:00:00+00:00",
        "count": len(routes),
        "stats": {"routes": len(routes),
                  "fully_funded": sum(1 for r in routes if r["fully_funded"])},
        "defaults": CFG.get("defaults") or {},
        "pipeline": doctoral.pipeline_entries(PIPE),
        "routes": routes,
    }
    # Written to a scratch file on purpose. docs/data/phd.json is real data or
    # nothing: fixtures that reach it would be served from GitHub Pages as
    # though they were vacancies, which is the exact mistake the demo rows made
    # on this project's first live run.
    out = Path(tempfile.gettempdir()) / "phjobs-phd-fixture.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    reread = json.loads(out.read_text(encoding="utf-8"))
    check("phd.json round-trips", reread["count"] == len(routes))
    check("the page will find a routes array and a pipeline array",
          isinstance(reread["routes"], list) and isinstance(reread["pipeline"], list))
    check("no fixture is left in the published data directory",
          not (ROOT / "docs" / "data" / "phd.json").exists()
          or "fixture" not in (ROOT / "docs" / "data" / "phd.json").read_text(encoding="utf-8"))
    print(f"  wrote {out}")


if __name__ == "__main__":
    test_sitemaps()
    test_funding()
    test_eligibility()
    test_detection()
    test_pipeline()
    test_outputs()
    test_end_to_end()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
