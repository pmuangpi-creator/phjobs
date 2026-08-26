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

---

## Sources

| Source | How it is read | Confidence |
|---|---|---|
| ReliefWeb | Documented public API, no key ([apidoc.reliefweb.int](https://apidoc.reliefweb.int)) | Confirmed against the docs |
| Greenhouse boards | `boards-api.greenhouse.io`, the endpoint employers' own careers pages call | Endpoint pattern is well known; the specific board tokens in the config are guesses |
| Lever boards | `api.lever.co/v0/postings`, same idea | Same |
| RSS and Atom feeds | Whatever `config/sources.yaml` lists | Every feed URL is a guess |

Read that last column carefully. **ReliefWeb is the only source whose API I could
confirm.** The machine that wrote this repo had no network route to any of the
others, so no feed URL and no board token here has ever been fetched. They are
plausible candidates, not verified ones.

This is why every adapter fails soft. A dead source logs an error, contributes
zero jobs, and never breaks a run. After your first run, open the **Source
health** panel at the bottom of the page, or `docs/data/sources_status.json`, and
you will see exactly which ones are real. Delete the dead ones or set
`enabled: false`.

ReliefWeb alone carries a large share of the NGO, INGO and UN humanitarian
listings, so the board is useful even if every other source turns out to be
wrong. The academic and PhD side is the fragmented part and will need the most
pruning.

Deliberately not included: Devex and Impactpool (subscription), LinkedIn and
Indeed (terms of service prohibit this), FindAPhD (same). Adding them would mean
scraping against their terms.

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
