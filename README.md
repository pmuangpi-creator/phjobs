# Public Health Jobs Board

A self-updating board of public health vacancies: PhD positions, research
assistant and associate posts, NGO and INGO programme roles, UN and multilateral
jobs, and anything else in health that the filters catch.

Four times a day a GitHub Actions workflow pulls from every configured source,
throws away everything that is not public health, scores what remains against a
profile you control, merges it with the previous run so that "new since Tuesday"
means something, and commits a JSON file. GitHub Pages serves a single static
page that reads it. No server, no database, no API keys, no cost.

**Start here:** [SETUP.md](SETUP.md) walks through getting it live.

---

## What it looks like

One page. A search box, a sidebar of filters, and a list of cards. Five tabs
across the top: everything, new since your last visit, closing within seven
days, saved, and the ones you have marked not relevant.

Each card shows the category, how many days until it closes, seniority, contract
type and the themes that matched, over a relevance score in the corner. Save it,
hide it, expand the full description, or hit **Copy tracker row** to put a
tab-separated line on your clipboard in the exact column order of your existing
job application tracker. **Export CSV** does the same for everything currently
on screen.

Saved and hidden jobs live in your browser's local storage. They never leave
your machine and they are per-browser, so saving on your laptop will not show up
on your phone.

**LMIC** is two separate tags, because they answer different questions. *Based in
an LMIC* comes from the World Bank income classification, fetched from their API
on every run rather than hardcoded, since they re-classify every July. *LMIC
focus* means the work is about low- and middle-income settings wherever it sits,
so a post at LSHTM on TB in Malawi carries it. A job can have both.

**Copy view link** puts the current filter set in the URL. Bookmark it, and
"LMIC-based PhD positions closing this month" is one click instead of six.

**Calendar** copies the URL of `data/deadlines.ics`. Add it once in Google
Calendar under *Other calendars, +, From URL* and every closing date above your
score threshold appears in your calendar, with a reminder three days out. Each
refresh updates it.

**The digest** arrives as a GitHub issue on the repository, which GitHub emails
you because you watch your own repo. Nothing new above threshold and nothing
closing means no issue, so silence is meaningful. It reuses one open issue as a
thread rather than opening a new one every six hours; close it and the next
digest starts a fresh one. Thresholds live under `alerts:` in
`config/sources.yaml`. No SMTP password ever goes in the repository.

---

## Sources

| Source | Covers | How it is read |
|---|---|---|
| ReliefWeb | NGO, INGO and UN humanitarian health vacancies. The largest single source. | Documented public API v2, no key ([apidoc.reliefweb.int](https://apidoc.reliefweb.int)) |
| Workday | PATH, FHI 360, Management Sciences for Health | The JSON endpoint each employer's own careers page calls |
| SmartRecruiters | Population Services International | Documented public postings API, no key |
| Greenhouse | Dimagi, ONE Campaign, Resolve to Save Lives | `boards-api.greenhouse.io`, no key |
| RSS | jobRxiv (PhD, postdoc, RA, scientist, faculty, plus keyword searches), LSHTM including the MRC units in The Gambia and Uganda, KEMRI-Wellcome, and NGO Jobs in Africa country feeds | Plain feeds listed in `config/sources.yaml` |
| BambooHR | IDinsight (India, Philippines, Indonesia, Senegal, Kenya, Zambia) | Public careers JSON, no key |
| Workable | Evidence Action, VillageReach | Public widget JSON, no key |
| Listing pages | Last Mile Health, Living Goods, OUCRU, Ifakara, icddr,b, ICMR, DevNetJobsIndia, Aga Khan University | Link harvesting, see below |

Those last eight publish no feed of any kind. Rather than eight parsers written
against markup nobody has inspected, which is how this project ended up with
fourteen dead Greenhouse tokens, `fetch/pagefetch.py` harvests the links on each
listing page, keeps the ones that read like job titles, and lets the relevance
gate do the rest. Noisier than a bespoke parser and much harder to break: a site
redesign changes the noise level instead of silently returning nothing. Where a
site's job URLs have an obvious shape, a `link_pattern` regex in the config cuts
the noise to zero. `python3 run_refresh.py --discover <url>` prints a page's link
shapes to help you write one.

Every entry in `config/sources.yaml` has now either returned data in a live run
or been verified by fetching it. The speculative list this project started with
is gone; what each candidate actually returned is recorded in the GRAVEYARD
comment at the bottom of that file, so nobody re-adds a dead source in six
months.

Two things worth knowing about the ReliefWeb entry. Its v1 endpoint was
decommissioned mid-project and now answers 410 Gone, which is why the config
points at v2. And since 1 November 2025 ReliefWeb asks that the `appname`
parameter be pre-approved through a short form linked from
[their parameter docs](https://apidoc.reliefweb.int/parameters). Request one and
put it in the config; the self-descriptive name in there now may or may not keep
working.

Every adapter fails soft. A dead source logs an error, contributes zero jobs, and
never breaks a run. The **Source health** panel at the bottom of the page, and
`docs/data/sources_status.json`, show what each one returned on the last run.

Deliberately not included, on terms rather than on capability: Devex and
Impactpool (subscription), LinkedIn and Indeed (terms prohibit it), FindAPhD
(same), unjobs.org and Times Higher Education Unijobs (both have feeds, both
disallow automated retrieval in robots.txt).

Still missing, and each needing its own adapter: CHAI and Jhpiego are on iCIMS,
Vital Strategies on Taleo, IntraHealth on UKG, Population Council on Paylocity,
Abt on Oracle Fusion, Palladium on Cornerstone. All are JS-rendered, so they
would need a headless browser rather than an HTTP call.

---

## Tuning it

Two files. No code.

**`config/profile.yaml`** decides what appears and what floats to the top.

- `health_gate` is a list of substrings. A posting must match at least one to
  count as public health at all. It is deliberately generous: a board with a few
  irrelevant rows is a nuisance, a board that silently swallows the job you
  wanted is worthless. If something you wanted got dropped, add the word that
  would have caught it.
- `theme_weights`, `country_weights`, `category_weights` add points.
  `negative_weights` subtracts them when matched in the title. Scores only sort;
  they never remove anything.
- `language_flags` marks postings demanding a language you do not read. It flags,
  it does not filter.

Right now the weights lean toward TB, HIV, harm reduction, implementation
research, NCDs, climate and health, humanitarian and conflict-affected settings,
epidemiology and biostatistics, with location weight on Myanmar, Thailand,
Singapore, the Netherlands, Germany, the UK and Australia. Change any of it.

**`config/sources.yaml`** decides where postings come from. Adding a source is a
four-line edit:

```yaml
    - name: Some university feed
      url: https://example.edu/jobs/feed
      default_category: research
      enabled: true
```

Finding tokens for the employer boards:

- Careers page at `job-boards.greenhouse.io/foo` or `boards.greenhouse.io/foo`
  means the Greenhouse board token is `foo`.
- Careers page at `jobs.lever.co/bar` means the Lever company token is `bar`.

---

## Running it yourself

```bash
pip3 install -r requirements.txt

python3 run_refresh.py              # fetch everything, write docs/data/
python3 run_refresh.py --dry-run    # fetch and report, write nothing
python3 run_refresh.py --only rss   # one source group: reliefweb|greenhouse|lever|rss
python3 run_refresh.py --demo       # six invented postings, so the page renders offline
python3 run_refresh.py -v           # verbose

python3 selftest.py                 # 38 offline assertions, no network needed
```

To look at the page locally:

```bash
cd docs && python3 -m http.server 8000
# then open http://localhost:8000
```

Opening `docs/index.html` by double-clicking will not work. The page fetches
`data/jobs.json`, and browsers block that over `file://`.

The repository ships with demo data in `docs/data/jobs.json` so the page has
something to render before your first real run. Those six postings are invented,
the page shows an orange banner saying so, and the first successful fetch
overwrites them.

---

## How it fits together

```
run_refresh.py
   |
   +-- fetch/reliefweb.py    POST the jobs endpoint, paginate, normalise
   +-- fetch/boards.py       Greenhouse and Lever, one request per org
   +-- fetch/rssfeeds.py     whatever sources.yaml lists, parsed by feedparser
   |        |
   |        v  every adapter returns the same record shape, built by fetch/common.job()
   |
   +-- pipeline/classify.py  gate -> category -> region -> themes -> score
   +-- pipeline/merge.py     dedupe, expire, carry first_seen across runs
   |
   +-- docs/data/jobs.json           read by the page
   +-- docs/data/sources_status.json read by the Source health panel
```

Adapters know nothing about relevance. They fetch and normalise. Every judgement
about what matters happens in `pipeline/`, so changing your mind about scoring
never means touching a fetcher.

Three design decisions worth knowing about:

**An empty fetch never wipes the board.** If every source fails, the run exits
non-zero and leaves the existing data file alone. If one source fails, jobs it
supplied last time are carried forward for up to 45 days and marked
*unconfirmed* on the card.

**Closed vacancies disappear** two days after their stated deadline. The grace
period absorbs timezone slop in the source data.

**The same vacancy on two sources collapses to one card**, matched on normalised
title plus organisation plus country. The employer's own board wins over the
aggregator, because it links straight to the application form. The loser is
recorded in `also_on`.

---

## Known limitations

Country detection for RSS sources is a keyword scan over the title and summary,
because most feeds have no location field. It will miss and it will occasionally
guess wrong.

Category assignment is a regex over the title, falling back to the first 1500
characters of the description. A PhD position advertised as "Doctoral Researcher
(m/f/d)" is caught; one advertised only as "Scientific Employee" is not.

Deadlines come from the source. Several boards publish a date with no timezone.
Confirm on the original posting before you rely on one.

The relevance score is arithmetic over keyword hits. It is a sorting aid, not a
judgement about whether you should apply.

---

## Adding a new kind of source

`fetch/boards.py` is the shortest example: a function that takes config, returns
`(list_of_records, status_dict)`, and swallows its own exceptions. Build records
with `fetch.common.job()` so every field lands in the right place, then wire it
into `run_refresh.py` in the same shape as the existing four blocks.

Workday, SmartRecruiters and Ashby are the obvious next three. Several large
INGOs sit on those, each has a public JSON endpoint, and each is about forty
lines in this same pattern.
