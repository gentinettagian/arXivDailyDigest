# arXiv Daily Digest

A local web app that pulls the latest quant-ph / cond-mat submissions from
arXiv, filters them by keyword, and always flags papers where an author
matches one of your LinkedIn connections. Once a day, it also asks Claude
to pick out a few papers that seem particularly relevant to you. Abstracts
are truncated to 3 lines by default -- click one to expand it.

It runs silently in the background (via a macOS LaunchAgent, set up below)
starting at login -- no terminal window, no icon, nothing to launch by
hand. Just bookmark **`http://localhost:8765`** in Safari; click the
bookmark, click **Refresh now** whenever you want new papers, and edit
keywords/categories/connections path from the Settings panel in the
browser.

The page itself lives in [`index.html`](index.html), a real file you can
open and edit directly. It's served by `server.py` (which reads it straight
off disk, so any edits you make show up on reload).

## Why this has to run locally (not on a hosted server)

Two of the moving parts here can't run from a page hosted somewhere else:

- **arXiv fetching** -- a browser page can't make arbitrary cross-origin
  requests to arXiv's API for security reasons, so something has to fetch
  server-side.
- **Your LinkedIn connections** -- there's no public API for "give me my
  connections list." The only reliable way to get it is LinkedIn's own data
  export, which is a private file that should stay on your machine, not get
  uploaded anywhere.

So `server.py` runs a tiny web server on `127.0.0.1` only -- it's not
reachable from other machines, and nothing it reads (your connections CSV
included) ever leaves your computer.

## Setup

Requires Python 3.8+, no extra packages (standard library only). The
Claude suggestions feature additionally requires the `claude` CLI to be
installed and logged in (it already is, if you're reading this via Claude
Code) -- if it's ever missing, that feature just quietly disables itself;
everything else still works.

### 1. Get your LinkedIn connections export (optional, for the connection-matching feature)

1. LinkedIn → **Settings & Privacy → Data privacy → Get a copy of your data**
2. Select **Connections**, request the archive
3. LinkedIn emails you a download link (can take a few minutes to a day)
4. Unzip it -- you'll get `Connections.csv`

Note: LinkedIn's export only gives First/Last Name (no middle names or
consistent formatting), and arXiv author lists are often "F. Last" or don't
include middle names either. The matching logic handles the common cases
(exact full name, or last name + first initial) but won't be perfect --
review the flagged papers rather than trusting it blindly.

### 2. Start it

```bash
./install_launchagent.sh
```

This installs a macOS LaunchAgent that runs `server.py` silently in the
background, starting automatically at every future login too -- no
terminal window, no icon. Run it once from wherever you cloned this repo;
it works out the correct path automatically. Then just open
`http://localhost:8765` in Safari and bookmark it.

If you ever want to run it manually in the foreground instead (e.g. to
watch logs live while debugging), double-click **`Start arXiv Digest.command`**
in Finder, or run `python3 server.py` from a terminal. Stop the LaunchAgent
first if you do (see below) so the two don't fight over the same port.

### 3. Configure it from the browser

Open the **Settings** panel on the page and fill in:

| Field | Meaning |
|---|---|
| Keywords | One keyword/phrase per line, matched case-insensitively against title + abstract. Edited directly here and stored in `config.json` -- no separate file to maintain (seeded once from `keywords.txt` the first time the app runs). |
| LinkedIn connections CSV path | Absolute path to your `Connections.csv`. Leave blank to skip connection-matching. |
| Lookback (arXiv announcement days) | Only include papers from the N most recent arXiv *announcement* days (not a raw calendar-day cutoff -- see "How matching works" below). |
| Max results fetched | Cap on how many recent entries to consider per refresh, across all categories combined. |
| Categories | Comma-separated arXiv category codes. Full list: https://arxiv.org/category_taxonomy |

Click **Save settings**, then **Refresh now** to fetch. Settings persist in
`config.json`; the last fetched results persist in `cache.json` (both live
next to the script), so reopening the page later shows your last refresh
without hitting arXiv again.

## Claude's suggestions

The first time you load the page on a given calendar day, the server
kicks off a background job (`ai_insights.py`) that:

1. Refreshes the papers as usual.
2. Reads `~/.claude/preferences.md` and this project's saved Claude Code
   memory (as context, not instructions) to understand your interests.
3. Sends the day's matched papers (title + abstract) to Claude (Sonnet)
   via the `claude` CLI -- `claude -p` -- so it runs through your existing
   Claude Code login, no separate API key needed.
4. Asks it to pick up to 3 papers that seem particularly relevant to you,
   with a one-sentence reason each, shown in a blue **Claude's
   suggestions** section at the top of the page.

This only runs once per calendar day (tracked in `ai_insights.json`), the
first time you actually open the page that day -- not on every Refresh,
and not while you're not using it. While it's running, a small status
line says so; the page just shows no suggestions section until it
finishes (usually under a minute). If it fails for any reason (e.g. the
`claude` CLI isn't found, or you're logged out), the status line says so
and the rest of the page is unaffected.

Every paper's abstract is truncated to 3 lines by default -- click it (or
the "click to expand" hint underneath) to show the full text, click again
to collapse it back.

We looked at generating per-paper summaries with Apple's on-device
Foundation Models (would avoid any Claude cost for that part) but dropped
it after testing: sequential on-device calls took ~4x longer than Sonnet's
parallel-batched approach for a typical day's paper count, concurrent
on-device calls were slower still (the shared on-device model contends
with itself rather than parallelizing), and it fabricated a detail not
present in the source abstract in testing -- not something we want in a
research digest. Truncate-and-expand is simpler and has none of those
problems.

## Running in the background (macOS LaunchAgent)

`./install_launchagent.sh` (step 2 above) writes
`~/Library/LaunchAgents/com.arxivdigest.server.plist`, pointing it at
`server.py` in wherever you actually cloned this repo, and loads it -- it
runs `server.py --no-browser` with `RunAtLoad` and `KeepAlive`, so it
starts the moment you log in and restarts itself if it ever crashes. Logs
go to `/tmp/arxivdigest.log`.

Useful commands:

```bash
# check status
launchctl print "gui/$(id -u)/com.arxivdigest.server"

# stop it (e.g. before running server.py manually in a terminal)
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.arxivdigest.server.plist

# start it again
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.arxivdigest.server.plist

# remove it entirely (also delete the plist file afterwards if you want it gone for good)
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.arxivdigest.server.plist
rm ~/Library/LaunchAgents/com.arxivdigest.server.plist
```

If you move this project folder, just re-run `./install_launchagent.sh` --
it regenerates the plist with the new path.

## How matching works

- **Fetching**: pulls arXiv's own `/list/<category>/recent` listing pages
  (the same ones you'd browse at arxiv.org) rather than the search API.
  Those pages group papers by the *announcement* day arXiv actually
  assigns them -- which is not always the day the paper was first
  submitted. A paper can be submitted weeks before it's cross-listed into
  one of your tracked categories or cleared moderation, in which case
  arXiv (and this app) treats its *announcement* day as "new," even though
  its original submission date is much older. This also means replacements
  (revised versions of already-announced papers) are excluded automatically,
  and weekends are skipped, since arXiv doesn't announce anything then.
- **Keyword match**: substring search (case-insensitive) across title +
  abstract.
- **Connection match**: normalizes both arXiv author names and your
  connections list (lowercase, strip punctuation), then checks for an exact
  full-name match or a last-name + first-initial match. A paper is included
  if *either* condition is true -- connections always show up even with zero
  keyword matches.
- Papers are limited to the `Lookback` setting's N most recent
  *announcement* days, not a raw N*24-hour cutoff.

## Troubleshooting: "no papers show up"

If a refresh finds nothing, the message under Refresh tells you why: it
shows the most recent arXiv announcement day it could see, so you can tell
"nothing's been announced in your lookback window yet" apart from
"something's broken." The default lookback is 3 announcement days, which
comfortably spans a weekend; widen it further if you skip a Refresh for
several days.

## Limitations

- Matches title + abstract only, not full paper text (would require
  downloading and parsing every PDF -- too slow/fragile for a daily job).
- Name matching is approximate; check the "connection" tag rather than
  trusting it as fully authoritative.
- arXiv's API is polite-use -- don't set "max results" much above a few
  hundred or click Refresh many times per hour.

## CLI / cron mode (legacy)

`arxiv_scraper.py` still works as a one-shot script that writes a static
HTML file, if you'd rather schedule it with cron than run the web app:

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
