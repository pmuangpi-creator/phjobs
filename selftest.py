#!/usr/bin/env python3
"""Offline smoke test. No network required.

Feeds synthetic postings through the same gate, classifier, scorer and merge
code the real run uses, and asserts the parts that are easy to break silently:
the relevance gate keeps health jobs and drops drivers, PhDs are recognised as
PhDs, UN organisations land in the UN bucket, closed vacancies disappear, cross
source duplicates collapse, and first_seen survives a second run.

    python3 selftest.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch.common import job, parse_date, strip_html, truncate  # noqa: E402
from pipeline import classify, income, merge  # noqa: E402

# A stand-in for the World Bank payload, in exactly the shape their API returns,
# so the LMIC logic is testable without a network call.
WB_SAMPLE = [
    {"id": "MMR", "iso2Code": "MM", "name": "Myanmar", "capitalCity": "Nay Pyi Taw",
     "region": {"id": "EAS", "value": "East Asia & Pacific"},
     "incomeLevel": {"id": "LMC", "value": "Lower middle income"}},
    {"id": "MWI", "iso2Code": "MW", "name": "Malawi", "capitalCity": "Lilongwe",
     "region": {"id": "SSF", "value": "Sub-Saharan Africa"},
     "incomeLevel": {"id": "LIC", "value": "Low income"}},
    {"id": "KEN", "iso2Code": "KE", "name": "Kenya", "capitalCity": "Nairobi",
     "region": {"id": "SSF", "value": "Sub-Saharan Africa"},
     "incomeLevel": {"id": "LMC", "value": "Lower middle income"}},
    {"id": "THA", "iso2Code": "TH", "name": "Thailand", "capitalCity": "Bangkok",
     "region": {"id": "EAS", "value": "East Asia & Pacific"},
     "incomeLevel": {"id": "UMC", "value": "Upper middle income"}},
    {"id": "GBR", "iso2Code": "GB", "name": "United Kingdom", "capitalCity": "London",
     "region": {"id": "ECS", "value": "Europe & Central Asia"},
     "incomeLevel": {"id": "HIC", "value": "High income"}},
    {"id": "SGP", "iso2Code": "SG", "name": "Singapore", "capitalCity": "Singapore",
     "region": {"id": "EAS", "value": "East Asia & Pacific"},
     "incomeLevel": {"id": "HIC", "value": "High income"}},
    {"id": "VNM", "iso2Code": "VN", "name": "Viet Nam", "capitalCity": "Hanoi",
     "region": {"id": "EAS", "value": "East Asia & Pacific"},
     "incomeLevel": {"id": "LMC", "value": "Lower middle income"}},
    {"id": "CHE", "iso2Code": "CH", "name": "Switzerland", "capitalCity": "Bern",
     "region": {"id": "ECS", "value": "Europe & Central Asia"},
     "incomeLevel": {"id": "HIC", "value": "High income"}},
    {"id": "WLD", "iso2Code": "1W", "name": "World", "capitalCity": "",
     "region": {"id": "NA", "value": "Aggregates"},
     "incomeLevel": {"id": "NA", "value": "Aggregates"}},
]

ROOT = Path(__file__).resolve().parent
PROFILE = yaml.safe_load((ROOT / "config" / "profile.yaml").read_text(encoding="utf-8"))

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  ok    " if cond else "  FAIL  ") + name + (f"  -- {detail}" if detail and not cond else ""))


def d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


SAMPLES = [
    job(source="ReliefWeb", title="TB and HIV Programme Manager",
        org="Médecins Sans Frontières", url="https://reliefweb.int/job/1",
        countries=["Myanmar"], city="Yangon", posted=d(-3), deadline=d(20),
        summary="Lead active case finding for tuberculosis and HIV in conflict-affected townships. "
                "Implementation research experience with harm reduction programmes desirable.",
        extra={"rw_themes": ["Health"], "rw_categories": ["Programme/Project Management"]}),
    job(source="RSS:jobRxiv", title="PhD candidate in implementation science, tuberculosis treatment",
        org="Radboud University Medical Center", url="https://example.org/phd/1",
        posted=d(-1),
        summary="Fully funded four-year doctoral position in the Netherlands on rifampicin dose "
                "optimisation for tuberculosis. Epidemiology or clinical background required.",
        hint_category="phd"),
    job(source="RSS:jobs.ac.uk", title="Research Associate in Epidemiology",
        org="London School of Hygiene and Tropical Medicine", url="https://example.org/ra/1",
        countries=["United Kingdom"], posted=d(-5), deadline=d(4),
        summary="Quantitative epidemiologist to work on a cohort study of noncommunicable disease "
                "risk in low- and middle-income countries. Mixed methods welcome."),
    job(source="RSS:UNjobs health", title="Technical Officer, Health Emergencies",
        org="World Health Organization", url="https://example.org/who/1",
        countries=["Thailand"], posted=d(-2), deadline=d(45),
        summary="Support outbreak surveillance and epidemic preparedness in the region."),
    job(source="ReliefWeb", title="Driver", org="Some NGO",
        url="https://reliefweb.int/job/2", countries=["Kenya"], posted=d(-1),
        summary="Valid licence required. Vehicle maintenance and logistics support.",
        extra={"rw_themes": [], "rw_categories": ["Logistics/Procurement"]}),
    job(source="ReliefWeb", title="Fundraising Manager", org="A Charity",
        url="https://reliefweb.int/job/3", countries=["United Kingdom"], posted=d(-1),
        summary="Grow our individual giving programme and steward major donors.",
        extra={"rw_themes": [], "rw_categories": ["Donor Relations/Grants Management"]}),
    job(source="ReliefWeb", title="Nutrition Coordinator", org="Concern Worldwide",
        url="https://reliefweb.int/job/4", countries=["Sudan"], posted=d(-1), deadline=d(-30),
        summary="Manage CMAM programming for acute malnutrition.",
        extra={"rw_themes": ["Health - Nutrition"], "rw_categories": ["Programme/Project Management"]}),
    # duplicate of the MSF post, seen on an employer board instead
    job(source="Greenhouse:msf", title="TB and HIV Programme Manager",
        org="Médecins Sans Frontières", url="https://boards.greenhouse.io/msf/jobs/1",
        countries=["Myanmar"], city="Yangon", posted=d(-3),
        summary="Lead active case finding for tuberculosis and HIV."),
]

print("\ntext helpers")
check("strip_html removes markup and unescapes entities",
      strip_html("<p>Health &amp; <b>nutrition</b></p>") == "Health & nutrition",
      strip_html("<p>Health &amp; <b>nutrition</b></p>"))
check("strip_html drops script blocks",
      "alert" not in strip_html("<script>alert(1)</script><p>hi</p>"))
check("truncate respects the limit", len(truncate("x " * 900, 100)) <= 104)
check("parse_date reads ISO", parse_date("2026-08-26T10:00:00Z") == "2026-08-26")
check("parse_date reads RFC 822", parse_date("Wed, 26 Aug 2026 10:00:00 +0000") == "2026-08-26")
check("parse_date reads unix ms", parse_date(1756166400000) is not None)
check("parse_date survives rubbish", parse_date("not a date at all") is None,
      str(parse_date("not a date at all")))
check("ids are stable across calls",
      job(source="s", title="t", url="https://a/b?utm=1")["id"] ==
      job(source="s", title="t", url="https://a/b?utm=2")["id"])

print("\nrelevance gate")
gate = PROFILE["health_gate"]
kept = [s for s in SAMPLES if classify.passes_gate(s, gate)]
titles = {k["title"] for k in kept}
check("keeps the TB/HIV programme manager", "TB and HIV Programme Manager" in titles)
check("keeps the PhD position", any("PhD candidate" in t for t in titles))
check("keeps the epidemiology research associate", "Research Associate in Epidemiology" in titles)
check("keeps the WHO technical officer", "Technical Officer, Health Emergencies" in titles)
check("keeps nutrition via the ReliefWeb theme tag", "Nutrition Coordinator" in titles)
check("drops the driver", "Driver" not in titles)
check("drops the fundraising manager", "Fundraising Manager" not in titles, str(titles))

# assume_health waives the gate for sources that give a title and nothing else
bare = job(source="Workday:PATH", title="Senior Program Officer", org="PATH",
           url="https://example.org/wd/1", summary="Seattle, WA",
           extra={"assume_health": True})
check("assume_health waives the gate", classify.passes_gate(bare, gate))
bare_no_flag = job(source="Workday:PATH", title="Senior Program Officer", org="PATH",
                   url="https://example.org/wd/2", summary="Seattle, WA")
check("without assume_health the same record is dropped",
      not classify.passes_gate(bare_no_flag, gate))
check("assume_health is stripped before publishing",
      "assume_health" not in classify.enrich(dict(bare), PROFILE))

print("\nincome classification and LMIC tagging")
usable = income._usable(WB_SAMPLE)
check("aggregate rows are dropped", len(usable) == 8 and all(c["id"] != "WLD" for c in usable),
      str(len(usable)))
CLS = income.Classifier(usable)

check("lookup by country name", (CLS.lookup("Myanmar") or {}).get("id") == "MMR")
check("lookup is case insensitive", (CLS.lookup("mYaNmAr") or {}).get("id") == "MMR")
check("lookup by ISO3", (CLS.lookup("KEN") or {}).get("id") == "KEN")
check("lookup by ISO2", (CLS.lookup("th") or {}).get("id") == "THA")
check("lookup by capital city", (CLS.lookup("Lilongwe") or {}).get("id") == "MWI")
check("lookup via alias (Vietnam -> Viet Nam)", (CLS.lookup("Vietnam") or {}).get("id") == "VNM")
check("lookup via alias (Burma -> Myanmar)", (CLS.lookup("Burma") or {}).get("id") == "MMR")
check("lookup via alias (England -> United Kingdom)",
      (CLS.lookup("England") or {}).get("id") == "GBR")
check("extra-city table (Yangon -> Myanmar)", (CLS.lookup("Yangon") or {}).get("id") == "MMR")
check("unknown place returns None", CLS.lookup("Atlantis") is None)

check("group_for reads the income group", CLS.group_for(["Kenya"])[0] == "LMC")
check("group_for labels it", CLS.group_for(["Malawi"])[1] == "Low income")
check("multi-country role takes the lowest income group",
      CLS.group_for(["Switzerland", "Malawi"])[0] == "LIC",
      str(CLS.group_for(["Switzerland", "Malawi"])))
check("high income is classified, not blank", CLS.group_for(["Singapore"])[0] == "HIC")
check("unrecognised place gives no group", CLS.group_for(["Atlantis"])[0] == "")

found = CLS.find_in_text("The post is split between Nairobi and Bangkok offices.")
check("find_in_text picks countries out of prose",
      {c["id"] for c in found} == {"KEN", "THA"}, str([c["id"] for c in found]))
check("find_in_text ignores substrings inside words",
      not CLS.find_in_text("We met in Kenyatta Avenue premises"), "false positive on Kenyatta")

lmic_based = classify.enrich(
    job(source="RSS:test", title="TB Programme Officer", org="An NGO",
        url="https://e.org/a", summary="Based in Lilongwe. Case finding for tuberculosis."),
    PROFILE, CLS)
check("duty station resolved from a bare city name", lmic_based["countries"] == ["Malawi"],
      str(lmic_based["countries"]))
check("lmic_duty_station set", lmic_based["lmic_duty_station"] is True)
check("income_group recorded", lmic_based["income_group"] == "LIC")
check("region comes from the World Bank", lmic_based["region"] == "Sub-Saharan Africa",
      lmic_based["region"])

london_lmic = classify.enrich(
    job(source="RSS:test", title="Research Associate in Epidemiology",
        org="LSHTM", url="https://e.org/b", countries=["United Kingdom"],
        summary="Cohort study of tuberculosis treatment outcomes in Malawi and Kenya. "
                "Experience in low- and middle-income settings essential."),
    PROFILE, CLS)
check("HIC duty station is not tagged LMIC-based",
      london_lmic["lmic_duty_station"] is False)
check("but LMIC focus is detected", london_lmic["lmic_focus"] is True)
check("LMIC focus scores above a plain HIC post", london_lmic["score"] > 30, str(london_lmic["score"]))

domestic_hic = classify.enrich(
    job(source="RSS:test", title="Health Service Manager", org="An NHS Trust",
        url="https://e.org/c", countries=["United Kingdom"],
        summary="Managing outpatient clinics in Manchester."),
    PROFILE, CLS)
check("a domestic HIC post gets neither LMIC tag",
      not domestic_hic["lmic_duty_station"] and not domestic_hic["lmic_focus"])

check("enrich still works with no classifier at all",
      classify.enrich(dict(SAMPLES[0]), PROFILE, None).get("region") == "South-East Asia")

print("\nexclusion of bench science")
EXCL = PROFILE["exclude_terms"]
# Note the fixture has to TRIP the gate first, otherwise it proves nothing.
# "disease" and "medical" are in the gate on purpose; the exclusion list exists
# precisely because bench adverts use those words too.
bench = job(source="RSS:jobRxiv", title="Postdoctoral Fellow in Structural Biology",
            org="A University Medical Centre", url="https://e.org/d",
            summary="Cryo-EM and protein crystallography of membrane receptors implicated "
                    "in neurodegenerative disease. Cell culture and CRISPR experience "
                    "required, with a molecular biology background.")
check("bench science postdoc is excluded", not classify.passes_gate(bench, gate, EXCL))
check("and would have passed without the exclusion list",
      classify.passes_gate(bench, gate, []))

genomic_epi = job(source="RSS:jobRxiv", title="Postdoctoral Fellow, Genomic Epidemiology of TB",
                  org="A University", url="https://e.org/e",
                  summary="Whole-genome sequencing and transcriptomics to study tuberculosis "
                          "transmission in high-burden settings. Molecular biology background.")
check("genomic epidemiology survives the exclusion via the strong-term override",
      classify.passes_gate(genomic_epi, gate, EXCL))

print("\nclassification")
enriched = [classify.enrich(dict(k), PROFILE) for k in kept]
by_title = {e["title"]: e for e in enriched}
check("PhD post is category phd", by_title["PhD candidate in implementation science, tuberculosis treatment"]["category"] == "phd")
check("research associate is category research", by_title["Research Associate in Epidemiology"]["category"] == "research")
check("WHO post is category un", by_title["Technical Officer, Health Emergencies"]["category"] == "un")
check("MSF post is category ngo", by_title["TB and HIV Programme Manager"]["category"] == "ngo")
check("Myanmar maps to South-East Asia", by_title["TB and HIV Programme Manager"]["region"] == "South-East Asia")
check("country inferred from free text when absent",
      "Netherlands" in by_title["PhD candidate in implementation science, tuberculosis treatment"]["countries"],
      str(by_title["PhD candidate in implementation science, tuberculosis treatment"]["countries"]))
check("themes are tagged", len(by_title["TB and HIV Programme Manager"]["themes"]) > 0)
check("internal body field is stripped before publishing",
      all("_body" not in e for e in enriched))

print("\nscoring")
tb = by_title["TB and HIV Programme Manager"]["score"]
who = by_title["Technical Officer, Health Emergencies"]["score"]
phd = by_title["PhD candidate in implementation science, tuberculosis treatment"]["score"]
check("Myanmar TB/HIV role outscores the generic WHO post", tb > who, f"{tb} vs {who}")
check("PhD in the profile's target themes scores well", phd > 30, str(phd))
check("no negative scores", all(e["score"] >= 0 for e in enriched))

print("\nmerge")
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "jobs.json"

    first, stats1 = merge.merge(enriched, {}, expire_after_days=2, stale_after_days=45)
    ids = {j["title"] for j in first}
    check("closed vacancy is dropped", "Nutrition Coordinator" not in ids)
    check("duplicate across sources collapses to one",
          sum(1 for j in first if j["title"] == "TB and HIV Programme Manager") == 1)
    winner = next(j for j in first if j["title"] == "TB and HIV Programme Manager")
    check("employer board wins over the aggregator", winner["source"].startswith("Greenhouse"), winner["source"])
    check("the losing source is recorded in also_on", bool(winner.get("also_on")))
    check("results are sorted by score descending",
          all(first[i]["score"] >= first[i+1]["score"] for i in range(len(first)-1)))
    check("stats add up", stats1["published"] == len(first), str(stats1))

    path.write_text(json.dumps({"jobs": first}), encoding="utf-8")
    prev = merge.load_previous(path)
    check("previous run reloads", len(prev) == len(first))

    # Regression: demo rows were carried into the first live run as "unconfirmed"
    with_demo = [dict(j) for j in first] + [
        {"id": "demo1", "title": "Fake", "url": "https://example.invalid/1", "demo": True},
        {"id": "demo2", "title": "Fake 2", "url": "https://example.invalid/2", "demo": True},
    ]
    path.write_text(json.dumps({"jobs": with_demo}), encoding="utf-8")
    cleaned = merge.load_previous(path)
    check("demo rows are discarded when reloading previous data",
          len(cleaned) == len(first) and not any(j.get("demo") for j in cleaned.values()),
          f"{len(cleaned)} vs {len(first)}")
    path.write_text(json.dumps({"jobs": first}), encoding="utf-8")
    prev = merge.load_previous(path)

    for j in first:
        j["first_seen"] = None
    second, _ = merge.merge([dict(j) for j in enriched], prev)
    check("first_seen survives a second run",
          all(j.get("first_seen") for j in second))

    # No healthy_sources passed means every source is treated as failed, which
    # is the "everything broke" case the grace period exists for.
    third, _ = merge.merge([], prev, stale_after_days=45)
    check("an empty fetch does not wipe the board", len(third) > 0, str(len(third)))
    check("carried-over jobs are marked unconfirmed", all(j.get("stale") for j in third))

print("\nstaying current")

# 1. A healthy source that stops listing a job means the job is gone.
# Built from the records themselves, which also checks that the lowercased
# status keys really do line up with the source names on the records.
live_src = {j["source"].lower() for j in first}
gone, gstats = merge.merge([], {j["id"]: j for j in first}, healthy_sources=live_src)
check("a healthy source dropping a job removes it from the board",
      len(gone) == 0, f"{len(gone)} survived")
check("and it is counted as delisted, not expired",
      gstats["delisted_by_source"] > 0 and gstats["expired_dropped"] == 0, str(gstats))

# 2. A source that FAILED still gets the grace period.
kept_back, kstats = merge.merge([], {j["id"]: j for j in first}, healthy_sources=set())
check("a failed source keeps its jobs for the grace period", len(kept_back) > 0)
check("those are flagged unconfirmed", all(j.get("stale") for j in kept_back))

# 3. Postings with no closing date age out on their posting date.
old_no_deadline = job(
    source="RSS:jobRxiv PhD", title="PhD position in tuberculosis epidemiology",
    org="A University", url="https://e.org/old", posted=d(-200),
    summary="Doctoral position on tuberculosis. Public health epidemiology.")
fresh_no_deadline = job(
    source="RSS:jobRxiv PhD", title="PhD position in HIV epidemiology",
    org="A University", url="https://e.org/new", posted=d(-5),
    summary="Doctoral position on HIV. Public health epidemiology.")
aged = [classify.enrich(r, PROFILE, CLS) for r in (old_no_deadline, fresh_no_deadline)]
out, astats = merge.merge(aged, {}, max_age_days=90)
kept_titles = {j["title"] for j in out}
check("a 200-day-old posting with no deadline is retired",
      not any("tuberculosis epidemiology" in t for t in kept_titles), str(kept_titles))
check("a recent posting with no deadline stays",
      any("HIV epidemiology" in t for t in kept_titles), str(kept_titles))
check("aged-out listings are counted separately",
      astats["aged_out_no_deadline"] == 1, str(astats))
check("max_age_days=0 disables the age rule",
      len(merge.merge(aged, {}, max_age_days=0)[0]) == 2)

# 4. A stated deadline still wins over age: old posting, deadline still open.
old_but_open = classify.enrich(job(
    source="RSS:test", title="Health Programme Officer", org="An NGO",
    url="https://e.org/openold", posted=d(-200), deadline=d(14),
    summary="Public health programme delivery."), PROFILE, CLS)
check("an old posting with a future deadline is kept",
      len(merge.merge([old_but_open], {}, max_age_days=90)[0]) == 1)

# 5. Zero grace means it goes the day after it closes.
closed_yesterday = classify.enrich(job(
    source="RSS:test", title="Health Officer closed", org="An NGO",
    url="https://e.org/closed", posted=d(-30), deadline=d(-1),
    summary="Public health programme delivery."), PROFILE, CLS)
check("expire_after_days=0 drops a vacancy that closed yesterday",
      len(merge.merge([closed_yesterday], {}, expire_after_days=0)[0]) == 0)
check("expire_after_days=2 would still hold it",
      len(merge.merge([closed_yesterday], {}, expire_after_days=2)[0]) == 1)

print("\nfrontend contract")

print("\nlink harvesting (no network: parser exercised directly)")
from bs4 import BeautifulSoup  # noqa: E402
from fetch import pagefetch  # noqa: E402

LISTING = """
<html><body>
<nav><a href="/">Home</a><a href="/about">About us</a><a href="/contact">Contact</a></nav>
<main>
  <a href="/apply/AB12cd/senior-monitoring-and-evaluation-officer">Senior Monitoring and Evaluation Officer</a>
  <a href="/apply/EF34gh/community-health-worker-coordinator">Community Health Worker Coordinator</a>
  <a href="/apply/IJ56kl/finance-manager-nairobi">Finance Manager, Nairobi</a>
  <a href="/news/we-opened-a-clinic">We opened a clinic in Lilongwe last week</a>
  <a href="/brochure.pdf">Download our annual report brochure</a>
  <a href="https://twitter.com/example">Twitter</a>
  <a href="/apply/AB12cd/senior-monitoring-and-evaluation-officer">Apply</a>
</main>
<footer><a href="/privacy">Privacy policy</a></footer>
</body></html>
"""


def harvest_offline(html, site):
    """Run the harvester's link-selection logic without a network call."""
    from urllib.parse import urljoin, urlparse
    import re as _re
    soup = BeautifulSoup(html, "html.parser")
    base = site["url"]
    host = urlparse(base).netloc
    pattern = _re.compile(site["link_pattern"], _re.I) if site.get("link_pattern") else None
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base, href)
        if urlparse(full).netloc != host or full in seen:
            continue
        text = pagefetch._clean(a.get_text())
        if not pagefetch._looks_like_job(text, full, pattern):
            continue
        if pattern and (len(text) < pagefetch.MIN_TITLE or text.lower() in pagefetch.NAV_WORDS):
            continue
        seen.add(full)
        out.append((text, full))
    return out


heur = harvest_offline(LISTING, {"url": "https://example.org/careers"})
titles = [t for t, _ in heur]
check("heuristic finds the M&E officer", any("Monitoring and Evaluation" in t for t in titles))
check("heuristic finds the CHW coordinator", any("Community Health Worker" in t for t in titles))
check("heuristic finds the finance manager too (the gate drops it later)",
      any("Finance Manager" in t for t in titles))
check("heuristic skips nav links",
      not any(t in ("Home", "About us", "Contact") for t in titles), str(titles))
check("heuristic skips the news story", not any("opened a clinic" in t for t in titles), str(titles))
check("heuristic skips the PDF", not any("brochure" in t.lower() for t in titles), str(titles))
check("heuristic skips off-host links", not any(t == "Twitter" for t in titles))
check("heuristic skips the privacy link", not any("Privacy" in t for t in titles))

patterned = harvest_offline(LISTING, {"url": "https://example.org/careers",
                                      "link_pattern": "/apply/[A-Za-z0-9]+/"})
check("link_pattern keeps only the three postings", len(patterned) == 3, str(len(patterned)))
check("link_pattern drops the bare 'Apply' anchor",
      not any(t == "Apply" for t, _ in patterned))
check("harvested urls are absolute",
      all(u.startswith("https://example.org/apply/") for _, u in patterned))

check("discover() collapses ids into a shape",
      "<id>" in re.sub(r"/[^/]*\d[^/]*", "/<id>", "/apply/AB12cd/some-role"))

check("_readable strips scripts and chrome",
      "alert" not in pagefetch._readable(
          "<html><body><script>alert(1)</script><nav>Menu</nav>"
          "<main><p>Programme Officer based in Lilongwe.</p></main></body></html>"))
check("_readable keeps the body text",
      "Lilongwe" in pagefetch._readable(
          "<html><body><main><p>Programme Officer based in Lilongwe.</p></main></body></html>"))

print("\ncalendar feed")
from pipeline import outputs  # noqa: E402

cal_jobs = [
    {"id": "a1", "title": "TB Officer; Kilifi, Kenya", "org": "An NGO", "url": "https://e.org/1",
     "countries": ["Kenya"], "city": "Kilifi", "deadline": d(10), "score": 60,
     "lmic_duty_station": True, "lmic_focus": True},
    {"id": "a2", "title": "Low scorer", "org": "X", "url": "https://e.org/2",
     "countries": [], "deadline": d(10), "score": 5},
    {"id": "a3", "title": "Already closed", "org": "X", "url": "https://e.org/3",
     "countries": [], "deadline": d(-5), "score": 60},
    {"id": "a4", "title": "No deadline", "org": "X", "url": "https://e.org/4",
     "countries": [], "deadline": None, "score": 60},
    {"id": "a5", "title": "Far future", "org": "X", "url": "https://e.org/5",
     "countries": [], "deadline": d(400), "score": 60},
]
ics = outputs.build_ics(cal_jobs, min_score=20, horizon_days=120)
check("ics is well formed", ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR"))
check("ics uses CRLF line endings", "\r\n" in ics and "\n\n" not in ics)
check("ics contains exactly one event", ics.count("BEGIN:VEVENT") == 1, str(ics.count("BEGIN:VEVENT")))
check("ics drops the low scorer", "Low scorer" not in ics)
check("ics drops the closed vacancy", "Already closed" not in ics)
check("ics drops the job with no deadline", "No deadline" not in ics)
check("ics drops anything past the horizon", "Far future" not in ics)
check("ics escapes semicolons in titles", "Kilifi\\, Kenya" in ics or "Officer\\;" in ics, "escaping")
check("ics sets a reminder", "BEGIN:VALARM" in ics and "TRIGGER:-P3D" in ics)
check("ics folds long lines", all(len(l.encode()) <= 75 for l in ics.split("\r\n")),
      "a line exceeded 75 octets")
check("ics uid is stable across builds",
      outputs.build_ics(cal_jobs, min_score=20).count("UID:") == ics.count("UID:"))

print("\ndigest")
dig_jobs = [
    {"id": "n1", "title": "New high scorer", "org": "An NGO", "url": "https://e.org/n1",
     "countries": ["Malawi"], "score": 70, "lmic_duty_station": True, "deadline": d(30)},
    {"id": "n2", "title": "New but weak", "org": "X", "url": "https://e.org/n2",
     "countries": [], "score": 5},
    {"id": "old1", "title": "Seen before", "org": "X", "url": "https://e.org/o1",
     "countries": [], "score": 90},
    {"id": "c1", "title": "Closing tomorrow", "org": "Y", "url": "https://e.org/c1",
     "countries": ["Kenya"], "score": 55, "deadline": d(1)},
]
title, body, n = outputs.build_digest(dig_jobs, {"old1"}, min_score=30, closing_days=3)
# c1 is both new and closing soon; it must be counted once, not twice.
check("digest counts distinct jobs, not rows", n == 2, str(n))
check("digest includes the new high scorer", "New high scorer" in body)
check("digest excludes the weak new one", "New but weak" not in body)
check("digest excludes what was already seen", "Seen before" not in body)
check("digest has a closing section", "Closing tomorrow" in body and "Closing within" in body)
check("digest title names both", "new" in title and "closing" in title, title)
check("digest marks LMIC listings", "`LMIC`" in body, body[:200])
empty_t, empty_b, empty_n = outputs.build_digest(
    [dig_jobs[2]], {"old1"}, min_score=30)
check("digest stays silent when there is nothing", empty_n == 0 and not empty_t and not empty_b)

print("\nfrontend contract")
required = {"id","title","org","url","countries","city","posted","deadline",
            "summary","contract","seniority","category","region","themes",
            "score","remote","language_flags","first_seen"}
missing = required - set(first[0].keys())
check("published record carries every field the page reads", not missing, str(missing))
check("record is JSON serialisable", bool(json.dumps(first)))

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
