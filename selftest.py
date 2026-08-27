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

    third, _ = merge.merge([], prev, stale_after_days=45)
    check("an empty fetch does not wipe the board", len(third) > 0, str(len(third)))
    check("carried-over jobs are marked unconfirmed", all(j.get("stale") for j in third))

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
