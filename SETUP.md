# Getting it live

Twenty minutes, once. After that it runs itself and you never touch it again
unless you want to change what it searches for.

Everything below is free on GitHub's personal tier.

---

## 1. Make a GitHub account

[github.com/signup](https://github.com/signup). Pick any username. Verify the
email. That is the whole step.

## 2. Make an empty repository

[github.com/new](https://github.com/new)

- **Repository name:** `phjobs`
- **Public** — required. GitHub Pages will not serve a private repository on the
  free tier. Nothing personal goes in this repo: it holds publicly-posted
  vacancies and the code that fetches them. Your saved and hidden jobs stay in
  your browser.
- Leave "Add a README", "Add .gitignore" and "Choose a license" **unticked**.
  You already have those files and GitHub will refuse the first push if the
  repository is not empty.
- **Create repository**

Leave that page open. You will need the URL, which looks like
`https://github.com/YOURNAME/phjobs`.

## 3. Upload the files

Two ways. Pick one.

### The easy way: GitHub Desktop

1. Download from [desktop.github.com](https://desktop.github.com) and install it.
2. Open it and sign in with the account from step 1.
3. **File → Add Local Repository**, choose the `phjobs` folder inside
   `Downloads/CLAUDE COWORK`.
4. It will say the folder is not a git repository and offer to create one.
   Say yes.
5. Type a summary in the bottom-left box, `first commit` is fine, and click
   **Commit to main**.
6. Click **Publish repository** at the top. Untick "Keep this code private".
   Publish.

GitHub Desktop handles the login for you, which is the part that trips people up
in the Terminal.

### The Terminal way

Open Terminal and run these, replacing `YOURNAME`:

```bash
cd ~/Downloads/CLAUDE\ COWORK/phjobs
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/YOURNAME/phjobs.git
git push -u origin main
```

Git will ask for a username and a password. **The password is not your GitHub
password** — GitHub stopped accepting those years ago. You need a token:

1. [github.com/settings/tokens](https://github.com/settings/tokens) →
   **Generate new token (classic)**
2. Tick **repo** and tick **workflow**. The `workflow` scope matters: without it
   GitHub refuses any push that contains a file under `.github/workflows/`, which
   is exactly what you are pushing.
3. Generate, copy the token, paste it as the password.

## 4. Let the workflow write back to the repository

The refresh job commits updated listings, so it needs write permission. This is
off by default.

**Settings → Actions → General → Workflow permissions** →
select **Read and write permissions** → **Save**.

Skip this and every run will fetch correctly, then fail on the final push with
a 403.

## 5. Turn on Pages

**Settings → Pages**

- **Source:** Deploy from a branch
- **Branch:** `main`, folder `/docs`
- **Save**

Your address is `https://YOURNAME.github.io/phjobs/`. It takes a minute or two
to appear the first time. Until the first fetch finishes you will see the demo
postings with an orange banner.

## 6. Run it once by hand

**Actions** tab → **Refresh jobs** in the left sidebar → **Run workflow** →
**Run workflow**.

If the Actions tab says workflows are disabled, click the button to enable them.
GitHub does this on new accounts.

Watch it run. Three to six minutes is normal; ReliefWeb pagination is the slow
part. Green tick means it worked.

## 7. Read the source health report

This is the step that actually matters, and the reason the previous step was
manual.

Open the finished run and look at the **Summary** page. At the bottom is a JSON
block listing every source and what it returned. Or open your site and expand
**Source health** at the bottom of the page.

Expect roughly this:

- `reliefweb` — `ok`, several hundred to a couple of thousand jobs. If this one
  failed, something is genuinely wrong and nothing else will save the board.
- Most `greenhouse:` and `lever:` entries — errors. Those tokens are guesses.
  See below.
- The `rss:` entries — a mix. Some feed URLs will be right, some will not.

Now prune. Open `config/sources.yaml` (you can edit it directly on GitHub: click
the file, then the pencil icon) and delete every source that errored, or set
`enabled: false`. Commit the change. That alone will cut the run time
substantially.

### Fixing a board token

If you know an organisation you want, go to their careers page and look at the
address bar:

- `job-boards.greenhouse.io/pih` or `boards.greenhouse.io/pih` → add `pih` under
  `greenhouse: boards:`
- `jobs.lever.co/dtree` → add `dtree` under `lever: companies:`
- Anything else → it is on Workday, SuccessFactors, Taleo or Oracle, none of
  which this version reads. Note it and we can add an adapter.

### Fixing a feed

Open the job board's search results page, view source, and look for
`type="application/rss+xml"`. That `href` is the feed URL. Paste it into
`config/sources.yaml`.

## 8. Leave it alone

From here the workflow runs at 01:00, 07:00, 13:00 and 19:00 UTC, which is
08:00, 14:00, 20:00 and 02:00 in Bangkok. The morning run has finished before
you open the page.

To change the cadence, edit the `cron:` line in
`.github/workflows/refresh.yml`. The times are UTC, always.

---

## Things that go wrong

**Actions tab shows a red X on the commit step, 403.**
Step 4. Workflow permissions are still read-only.

**Push rejected: "refusing to allow a Personal Access Token to create or update
workflow".**
The token is missing the `workflow` scope. Make a new one with it ticked.

**Push rejected: "Updates were rejected because the remote contains work that you
do not have locally".**
You ticked "Add a README" when creating the repository. Either delete the repo
and make an empty one, or run `git pull --rebase origin main` and push again.

**Site loads but says "No data file yet".**
The first workflow run has not finished, or it finished and every source failed.
Check the Actions tab.

**Site shows the orange demo banner.**
Same thing. No successful fetch has happened yet.

**Everything worked, then months later the schedule stopped.**
GitHub disables scheduled workflows on repositories that have gone quiet. I am
not certain whether the workflow's own commits count as activity, so if the
board goes stale, open the Actions tab and click **Run workflow** — that
re-enables it. Worth a look if you notice the timestamp has not moved in a week.

**A job you wanted is not on the board.**
Either no configured source carries it, or the relevance gate dropped it. Search
for the organisation on the page first. If nothing comes up, check whether that
employer is in `config/sources.yaml` at all. If the source is there and the job
is not, add a word to `health_gate` in `config/profile.yaml`.

---

## Making it public later

Nothing to do. The site is already a public URL. If you want other people to
find it, add a description and topics on the repository page, and consider
removing the personal weighting from `config/profile.yaml` so the default sort
is not tuned to one person's profile. The filters would carry the site on their
own.
