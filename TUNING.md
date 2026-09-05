# Changing what the board does

Almost everything is two files. You do not need to touch Python, and you do not
need a terminal: click any file on GitHub, hit the pencil icon, edit, then
**Commit changes**. That commit triggers a refresh by itself, so five minutes
later the board reflects your edit.

| I want to... | Edit |
|---|---|
| change what counts as a public health job at all | `config/profile.yaml` → `health_gate` |
| stop seeing a kind of job | `config/profile.yaml` → `exclude_terms` or `negative_weights` |
| change what floats to the top | `config/profile.yaml` → `theme_weights`, `country_weights`, `lmic_weights` |
| add or remove a job source | `config/sources.yaml` |
| change when the digest reaches me | `config/sources.yaml` → `alerts` |
| change what lands in my calendar | `config/sources.yaml` → `calendar` |
| change how often it runs | `.github/workflows/refresh.yml` → `cron` |

---

## The three settings you will actually use

### 1. Something you wanted is missing

The gate decides whether a posting is public health work at all. It is a list of
substrings, matched case-insensitively against the title, organisation and
description. If a job you wanted never appeared, add the word that would have
caught it:

```yaml
health_gate:
  - public health
  - epidemiolog
  - your new term here
```

Substrings, so `epidemiolog` catches epidemiology, epidemiologist and
epidemiological. Be generous. A board with a few irrelevant rows is a nuisance;
a board that silently swallows the job you wanted is worthless.

### 2. Something you keep seeing and do not want

Two different tools, and picking the wrong one is the usual mistake.

**`exclude_terms`** removes a posting entirely, unless it also carries an
unambiguous public health term. Use it for whole fields you never want:

```yaml
exclude_terms:
  - veterinary surgery
  - dental practice
```

**`negative_weights`** only pushes something down the ranking. Use it when the
job type is occasionally relevant but usually not:

```yaml
negative_weights:
  intern: -8
  fundraising: -6
  grant writer: -12
```

Reach for `negative_weights` first. Excluding is permanent and invisible; you
never see what you threw away.

### 3. The ordering is wrong

Points get added when a term is found. Nothing here removes a job, it only
sorts. To make Portugal-based roles surface, or to stop weighting Australia so
heavily:

```yaml
country_weights:
  portugal: 15
  australia: 4
```

Themes work the same way. If you decide health financing matters more than it
currently does:

```yaml
theme_weights:
  health financing: 10
```

And the LMIC weighting, which is the strongest single lever on this board:

```yaml
lmic_weights:
  duty_station: 25   # job is physically in a low/middle income country
  focus: 18          # work is ABOUT those settings, based anywhere
```

Raise `duty_station` and field roles dominate. Raise `focus` and the European
research and PhD posts climb. They stack, so a Nairobi role on TB gets both.

---

## Adding a source

Four shapes, depending on what the employer runs. Check their careers page URL
to work out which.

**A feed** (`.xml`, `/feed/`, `/rss`):

```yaml
rss:
  feeds:
    - name: Some institute
      url: https://example.org/jobs/feed
      default_category: research     # phd | research | ngo | un | gov
      enabled: true
```

**Greenhouse** — careers page at `job-boards.greenhouse.io/foo`:

```yaml
greenhouse:
  boards:
    - foo
```

**Lever** — careers page at `jobs.lever.co/bar`:

```yaml
lever:
  companies:
    - bar
```

**Workday** — careers page at `tenant.wd3.myworkdayjobs.com/SITENAME`:

```yaml
workday:
  sites:
    - name: Some INGO
      org: Some INGO
      host: tenant.wd3.myworkdayjobs.com
      tenant: tenant
      site: SITENAME
      assume_health: true
```

**No feed at all** — the fallback. Point it at the listing page and the
harvester takes the links that read like job titles:

```yaml
pages:
  sites:
    - name: Some employer
      org: Some employer
      url: https://example.org/careers
      country: Kenya          # optional, when the whole board is one country
      assume_health: true     # skip the gate; use only for health organisations
      enabled: true
```

If that source later reports *"no links looked like vacancies"*, the page needs
a hint. Run this locally and it prints the shape of every link on the page:

```bash
python3 run_refresh.py --discover https://example.org/careers
```

Then add the shape as a regex:

```yaml
      link_pattern: "/vacancies/[0-9]+/"
```

### `assume_health`, and when not to use it

It waives the relevance gate for a whole source. Correct for an organisation
that only does health work and whose board gives titles without descriptions.
Wrong for a general development board, where it floods you with logistics and
finance roles. When unsure, leave it off and add words to `health_gate` instead.

---

## The doctoral page

Two files, both editable without touching code.

### `config/phd_pipeline.yaml` — your own routes

The panel at the top of `phd.html`. Nothing here is fetched, scored or expired,
so it holds routes with no advert to fetch: a central doctoral application with
no deadline, a funding scheme, a supervisor you have written to.

```yaml
  - name: DAAD Research Grants, Doctoral Programmes in Germany
    institution: DAAD, via the Regional Office in Hanoi
    country: Germany
    funding: stipend            # salaried | stipend | partial | unfunded | unstated
    deadline: "2026-10-21"
    date_confidence: confirmed  # confirmed | inferred | none
    status: action              # action | sent | watching | closed
    affiliation: false          # does it need an employer at home
    next_action: >-
      Supervisor confirmation letter has to be in hand before the deadline.
```

`status` drives both the ordering and what shows by default: `action` and `sent`
are open on load, `watching` and `closed` are behind a link.

`date_confidence` is not decoration. `inferred` means the date is a pattern from
a previous cycle rather than something the institution has published, and the
page and the calendar both say so wherever that date appears. When you confirm
one on the institution's own page, change it to `confirmed` in the same edit.

### `config/phd.yaml` — how listings are read

Three keyword banks, each producing a label and the evidence behind it.

- `funding_terms.salaried` — employment language: salary scales, collective
  agreements, TV-L, CAO, "employed for four years".
- `funding_terms.stipend` — fees plus something to live on: "fully funded",
  "tax-free stipend", "UKRI rate", "covers tuition".
- `funding_terms.unfunded` — the vetoes: "self-funded", "fees only", "applicants
  must secure". These win, except that a listing carrying funded *and*
  self-funded language is labelled `partial` rather than either one.
- `affiliation_terms` — "home institution", "study leave", "sandwich", "must be
  nominated", "co-supervisor at".
- `nationality_terms` — "domestic applicants only", "home fee status",
  "Commonwealth citizens".

When a listing is labelled wrongly, open its card, read **why this label**, and
edit the phrase it names. Nothing here removes a listing; the page filters and
the pipeline labels, so a bad keyword costs you a wrong badge, never a route you
never saw.

`defaults:` sets what the page opens with. `fully_funded_only: true` is the
Fully funded tab; set it to `false` and the page opens on everything.

### One thing not to do

Do not add "no funding" or "unfunded" to `funding_terms.unfunded` on the
strength of a listing that simply says nothing about money. Silence has to stay
`unstated`. Dutch and Swedish doctoral posts are employment contracts whose
adverts often never mention pay, and reading that silence as "no money" deletes
the best routes on the board. If a whole source is salaried by construction, put
`assume_funding: salaried` on the source in `config/sources.yaml` instead.

---

## Alerts and calendar

```yaml
alerts:
  enabled: true
  min_score: 30        # a listing must score this to be worth telling you about
  closing_days: 3
```

Too many digests, raise `min_score`. None at all, lower it. Silence is
meaningful here: no issue is opened when nothing new clears the bar and nothing
is closing.

```yaml
calendar:
  min_score: 20        # deadlines below this stay out of your calendar
  horizon_days: 120
```

The doctoral track has its own pair, in `config/phd.yaml`, because its dates
behave differently. `data/phd_deadlines.ics` is a separate calendar you subscribe
to separately, carrying fully funded routes plus your own pipeline, and the
digest warns three weeks out rather than three days.

```yaml
calendar:
  horizon_days: 300
  fully_funded_only: true
digest:
  closing_days: 21
```

## Schedule

In `.github/workflows/refresh.yml`. Times are UTC, always.

```yaml
    - cron: "0 1,7,13,19 * * *"
```

That is 08:00, 14:00, 20:00 and 02:00 in Bangkok. For once a day at 07:00
Bangkok, use `"0 0 * * *"`.

---

## Checking before you commit

Nothing here can break the board permanently, because a failing source
contributes zero jobs and an empty fetch leaves the previous data alone. But if
you want to see the effect first, from the `phjobs` folder:

```bash
python3 selftest.py                 # 116 assertions, no network needed
python3 tests_doctoral.py           # 65 more, for the doctoral track
python3 run_refresh.py --dry-run    # fetch and report, write nothing
python3 run_refresh.py --only rss   # one source group at a time
```

`--dry-run` prints the top fifteen with their scores, which is the fastest way
to see whether a weighting change did what you meant.

---

## Reading the source health panel

At the bottom of the site, and in `docs/data/sources_status.json`.

- **`ok: N postings`** — working.
- **`error: 404`** — the token or URL is wrong. The organisation probably uses a
  different system than you assumed.
- **`error: returned 0 entries`** — reachable but not a feed. Usually an HTML
  page pretending to be one. Move it to `pages:` instead.
- **`error: no links looked like vacancies`** — the harvester found nothing
  job-shaped. Use `--discover` and add a `link_pattern`.
- **`error: 403`** — the host is refusing you. Check its robots.txt before
  working around it; several sources are deliberately excluded on that basis and
  the reasons are written in the GRAVEYARD comment at the bottom of
  `config/sources.yaml`.

## Worth knowing about the current state

Only about 30% of listings resolve to a country, because most feeds carry no
location field and the classifier has to read it out of the text. That caps how
much the LMIC duty-station filter can see. The fix is more `EXTRA_CITIES`
entries in `pipeline/income.py`, or narrower sources that state their country in
the config.

jobRxiv contributes the largest share of raw entries across its nine feeds, and
its keyword searches are loose OR-matching rather than phrase matching. If the
board feels academic-heavy, disabling the four `jobRxiv search ...` feeds is the
single biggest lever.
