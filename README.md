# arXiv Daily Digest

A local web app that pulls the latest arXiv submissions in your chosen
categories, filters them by keyword, and flags papers where an author
matches one of your LinkedIn connections. Once a day it also asks Claude
to pick out a few papers that seem particularly relevant to you, verified
against each paper's actual full text before being shown to you.

It runs silently in the background as a macOS LaunchAgent, starting at
login -- no terminal window, no icon. Bookmark `http://localhost:8765` in
Safari; click the bookmark, click **Refresh now** for new papers, and
configure everything from the Settings panel in the browser.

It runs entirely on your machine rather than a hosted server: arXiv
fetching needs a server-side request (a browser page can't do
cross-origin fetches to arXiv's API), and your LinkedIn connections file
is private and should never leave your computer. `server.py` only binds
to `127.0.0.1`.

## Setup

Requires Python 3.8+ (standard library only, no packages to install) and
macOS. The Claude suggestions feature additionally requires the `claude`
CLI installed and logged in -- if it's ever missing, that feature quietly
disables itself and everything else still works.

### 1. (Optional) Get your LinkedIn connections export

For the connection-matching feature:

1. LinkedIn → **Settings & Privacy → Data privacy → Get a copy of your data**
2. Select **Connections**, request the archive
3. LinkedIn emails you a download link (can take a few minutes to a day)
4. Unzip it -- you'll get `Connections.csv`

### 2. Install and start

```bash
./install_launchagent.sh
```

This installs a LaunchAgent that runs `server.py` in the background,
starting automatically at every future login, using whatever path you
cloned this repo to. Then open `http://localhost:8765` in Safari and
bookmark it.

To run it manually in the foreground instead (e.g. to watch logs while
debugging): stop the LaunchAgent first (see below), then double-click
`Start arXiv Digest.command`, or run `python3 server.py` from a terminal.

### 3. Configure it from the browser

Open the **Settings** panel and fill in:

| Field | Meaning |
|---|---|
| Keywords | One keyword/phrase per line, matched case-insensitively against title + abstract. |
| LinkedIn connections CSV path | Absolute path to your `Connections.csv`. Leave blank to skip connection-matching. |
| Lookback (arXiv announcement days) | Include papers from the N most recent arXiv *announcement* days (see "How it works" below). |
| Max results fetched | Cap on how many recent entries to consider per refresh, across all categories combined. |
| Categories | Comma-separated arXiv category codes. Full list: https://arxiv.org/category_taxonomy |

Click **Save settings**, then **Refresh now** to fetch.

## How it works

**Fetching**: pulls arXiv's own `/list/<category>/recent` listing pages
(the same ones you'd browse at arxiv.org), which group papers by the
*announcement* day arXiv assigns them -- not always the day a paper was
first submitted (a paper can be cross-listed into a new category weeks
after its original submission). Replacements (revised versions of
already-announced papers) are excluded, and weekends are skipped since
arXiv doesn't announce anything then. "Lookback" is a number of
announcement days, not a raw 24-hour cutoff.

**Matching**: every fetched paper is shown, tagged with any keyword
matches (case-insensitive substring search across title + abstract) and
whether an author matches your LinkedIn connections (exact name match, or
last name + first initial, to handle arXiv's "F. Last" author formatting).
Click a keyword tag below the Settings panel to filter the list down to
papers matching that keyword; your selection persists across reloads.
Every abstract is truncated to 3 lines by default -- click it to expand.

**Claude's suggestions**: the first time you load the page on a given
calendar day, a background job asks Claude (via the `claude` CLI, so it
uses your existing Claude Code login) to shortlist candidate papers based
on your interests -- read from `~/.claude/preferences.md` and this
project's saved Claude Code memory -- then fetches each candidate's full
HTML rendering from arXiv (which includes real author affiliations and
body text, unlike the abstract listing pages) and asks Claude to verify
each one before finalizing up to 3 picks, shown in a blue section at the
top of the page. This runs once per day, not on every Refresh; while
running, a status line says so.

## Troubleshooting: "no papers show up"

If a refresh finds nothing, the message under Refresh explains why,
showing the most recent arXiv announcement day it could see. The default
lookback is 3 announcement days, which comfortably spans a weekend; widen
it if you skip a Refresh for several days.

## Limitations

- Matches title + abstract only, not full paper text.
- Name matching for connections is approximate -- check the "connection"
  tag rather than trusting it as fully authoritative.
- arXiv's API is polite-use -- don't set "max results" much above a few
  hundred or click Refresh many times per hour.

## CLI / cron mode

`arxiv_scraper.py` is a one-shot script that writes a static HTML file,
for scheduling with cron instead of running the web app:

```bash
python3 arxiv_scraper.py \
  --keywords keywords.txt \
  --connections Connections.csv \
  --days 1 \
  --output arxiv_report.html
```

Then open `arxiv_report.html` in your browser. Run with `-h` for all
options. Both this and `server.py` share the same fetching/filtering logic
in `arxiv_core.py`.
