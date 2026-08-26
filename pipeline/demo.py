"""A handful of fabricated postings, so the page can be looked at before the
first real fetch has happened.

Every record carries demo: true and the page shows a banner saying so. These are
invented examples, not real vacancies, and the first successful run of
run_refresh.py overwrites the file entirely.
"""
from __future__ import annotations

from datetime import date, timedelta

from fetch.common import job


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def samples() -> list[dict]:
    return [
        job(
            source="ReliefWeb", title="TB and HIV Programme Manager",
            org="Example Humanitarian Organisation", url="https://example.invalid/demo/1",
            countries=["Myanmar"], city="Yangon", posted=_d(-3), deadline=_d(18),
            summary="DEMO RECORD, not a real vacancy. Lead mobile active case finding for "
                    "tuberculosis and HIV across conflict-affected townships, including harm "
                    "reduction services and implementation research on treatment retention.",
            contract="Fixed term",
            extra={"rw_themes": ["Health"], "rw_categories": ["Programme/Project Management"], "demo": True},
        ),
        job(
            source="RSS:jobRxiv", title="PhD candidate, implementation science and tuberculosis treatment",
            org="Example University Medical Center", url="https://example.invalid/demo/2",
            countries=["Netherlands"], posted=_d(-1), deadline=_d(35),
            summary="DEMO RECORD, not a real vacancy. Fully funded four-year doctoral position on "
                    "treatment optimisation, based in the Netherlands. Epidemiology or clinical "
                    "background required, mixed methods welcome.",
            hint_category="phd", extra={"demo": True},
        ),
        job(
            source="RSS:jobs.ac.uk", title="Research Associate in Epidemiology",
            org="Example School of Hygiene and Tropical Medicine", url="https://example.invalid/demo/3",
            countries=["United Kingdom"], city="London", posted=_d(-6), deadline=_d(5),
            summary="DEMO RECORD, not a real vacancy. Quantitative epidemiologist for a cohort "
                    "study of noncommunicable disease risk in low- and middle-income countries.",
            extra={"demo": True},
        ),
        job(
            source="RSS:UNjobs health", title="Technical Officer, Health Emergencies",
            org="World Health Organization", url="https://example.invalid/demo/4",
            countries=["Thailand"], city="Bangkok", posted=_d(-2), deadline=_d(44),
            summary="DEMO RECORD, not a real vacancy. Support outbreak surveillance, epidemic "
                    "preparedness and health systems capacity across the region.",
            extra={"demo": True},
        ),
        job(
            source="Greenhouse:example", title="Senior Research Associate, Health Economics",
            org="Example Global Health Institute", url="https://example.invalid/demo/5",
            countries=["Singapore"], city="Singapore", posted=_d(-4),
            summary="DEMO RECORD, not a real vacancy. Health technology assessment and economic "
                    "evaluation for communicable and non-communicable disease programmes.",
            extra={"demo": True},
        ),
        job(
            source="ReliefWeb", title="Nutrition Coordinator",
            org="Example Relief Agency", url="https://example.invalid/demo/6",
            countries=["Sudan"], city="Port Sudan", posted=_d(-8), deadline=_d(2),
            summary="DEMO RECORD, not a real vacancy. Manage community management of acute "
                    "malnutrition programming across five states.",
            extra={"rw_themes": ["Health - Nutrition"], "demo": True},
        ),
    ]
