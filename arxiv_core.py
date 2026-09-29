"""
Shared arXiv fetching/filtering logic used by both the CLI script
(arxiv_scraper.py) and the local web server (server.py).

Fetches arXiv's own /list/<category>/recent listing pages rather than the
export.arxiv.org search API. The search API's "published" field is the
paper's *original* submission date, which can lag its *announcement* date
by weeks (e.g. a paper cross-listed into a new category, or one held for
moderation) -- so filtering by "published within the last N days" misses
papers that arxiv.org's own site clearly shows as new today. The listing
pages group entries by the announcement day arxiv.org actually assigns
them, which is what "new papers" should mean here. They also already
exclude replacements (revised versions of older papers) and skip weekends
automatically, since arXiv doesn't announce anything on Sat/Sun.
"""

import csv
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

LISTING_BASE = "https://arxiv.org/list"
EXPORT_API = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ABSTRACT_BATCH_SIZE = 150

DEFAULT_CATEGORIES = [
    "quant-ph",
    "cond-mat.str-el",
    "cond-mat.supr-con",
    "cond-mat.mes-hall",
    "cond-mat.mtrl-sci",
    "cond-mat.stat-mech",
    "cond-mat.soft",
    "cond-mat.quant-gas",
    "cond-mat.dis-nn",
    "cond-mat.other",
]
# We list each cond-mat subcategory separately rather than relying on a
# cond-mat.* wildcard, since arXiv's listing pages are per exact category.


def _parse_listing_date(header_text):
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", header_text)
    if not m:
        return None
    day, mon, year = m.groups()
    try:
        return datetime.strptime(f"{day} {mon} {year}", "%d %b %Y").date()
    except ValueError:
        return None


def _clean_html_text(fragment):
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return " ".join(text.split())


def _parse_listing_entries(chunk):
    entries = []
    for dt_match in re.finditer(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", chunk, re.DOTALL):
        dt_html, dd_html = dt_match.groups()

        id_match = re.search(r'/abs/([^"\s]+)"', dt_html)
        if not id_match:
            continue
        arxiv_id = id_match.group(1)

        title_match = re.search(
            r"list-title mathjax'><span class='descriptor'>Title:</span>(.*?)</div>",
            dd_html, re.DOTALL,
        )
        title = _clean_html_text(title_match.group(1)) if title_match else ""

        authors_match = re.search(r"list-authors'>(.*?)</div>", dd_html, re.DOTALL)
        authors = []
        if authors_match:
            authors = [
                html.unescape(a).strip()
                for a in re.findall(r"<a[^>]*>([^<]*)</a>", authors_match.group(1))
            ]

        subjects_match = re.search(r"list-subjects'>(.*?)</div>", dd_html, re.DOTALL)
        categories = re.findall(r"\(([a-zA-Z0-9.\-]+)\)", subjects_match.group(1)) if subjects_match else []

        # Abstract text isn't in this listing view (/recent); fetch_recent_entries
        # fills it in afterwards via _fetch_abstracts.
        link = f"https://arxiv.org/abs/{arxiv_id}"
        entries.append({
            "id": link,
            "title": title,
            "summary": "",
            "authors": authors,
            "categories": categories,
            "link": link,
        })
    return entries


def _fetch_abstracts(arxiv_ids):
    """The listing pages we scrape for entries/dates don't include
    abstract text, so fetch it separately via the export API's id_list
    lookup -- a direct by-id fetch, so (unlike a date-sorted search) it
    reliably finds papers regardless of how old their original submission
    is. Returns {arxiv_id: summary}."""
    abstracts = {}
    ids = list(arxiv_ids)
    for i in range(0, len(ids), ABSTRACT_BATCH_SIZE):
        batch = ids[i:i + ABSTRACT_BATCH_SIZE]
        params = {"id_list": ",".join(batch), "max_results": len(batch)}
        url = f"{EXPORT_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "arxiv-scraper/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        for entry in root.findall(f"{ATOM_NS}entry"):
            raw_id = (entry.findtext(f"{ATOM_NS}id", default="") or "").strip()
            m = re.search(r"/abs/([0-9.]+)", raw_id)
            if not m:
                continue
            summary = " ".join((entry.findtext(f"{ATOM_NS}summary", default="") or "").split())
            abstracts[m.group(1)] = summary
    return abstracts


def fetch_recent_entries(categories, days):
    """Fetch the `days` most recent arXiv announcement days (new + cross-
    listed submissions) across the given categories. Returns
    (entries_within_days, total_entries_available, most_recent_date)."""
    merged = {}
    entry_dates = {}
    announcement_dates = set()

    for cat in categories:
        url = f"{LISTING_BASE}/{cat}/recent?skip=0&show=2000"
        req = urllib.request.Request(url, headers={"User-Agent": "arxiv-scraper/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", errors="replace")

        headers = list(re.finditer(r"<h3>([^<]*)</h3>", page))
        for i, header in enumerate(headers):
            date = _parse_listing_date(header.group(1))
            if date is None:
                continue
            start = header.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(page)
            announcement_dates.add(date)
            for entry in _parse_listing_entries(page[start:end]):
                existing = merged.get(entry["id"])
                if existing:
                    existing["categories"] = sorted(set(existing["categories"]) | set(entry["categories"]))
                else:
                    merged[entry["id"]] = entry
                    entry_dates[entry["id"]] = date

    if not announcement_dates:
        return [], 0, None

    most_recent = max(announcement_dates)
    cutoff_dates = set(sorted(announcement_dates, reverse=True)[:days]) if days else announcement_dates

    all_entries = sorted(merged.values(), key=lambda e: (entry_dates[e["id"]], e["id"]), reverse=True)
    within_cutoff = [e for e in all_entries if entry_dates[e["id"]] in cutoff_dates]

    abstracts = _fetch_abstracts(e["link"].rsplit("/", 1)[-1] for e in within_cutoff)
    for e in within_cutoff:
        e["summary"] = abstracts.get(e["link"].rsplit("/", 1)[-1], "")

    return within_cutoff, len(all_entries), most_recent


def load_keywords(keywords_arg):
    if not keywords_arg:
        return []
    p = Path(keywords_arg)
    text = p.read_text() if p.exists() else keywords_arg
    return parse_keywords_text(text)


def parse_keywords_text(text):
    """Split freeform keyword text (one per line, or comma-separated) into
    a clean list, dropping blanks and '#' comment lines."""
    if not text:
        return []
    parts = re.split(r"[\n,]", text)
    return [k.strip() for k in parts if k.strip() and not k.strip().startswith("#")]


def load_connections(path):
    """Load a LinkedIn 'Connections.csv' export. LinkedIn's export sometimes
    prepends a few 'Notes:' lines before the real header row, so we scan for
    the header rather than assuming it's row 0."""
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if "First Name" in line and "Last Name" in line:
            header_idx = i
            break
    reader = csv.DictReader(lines[header_idx:])
    names = []
    for row in reader:
        first = (row.get("First Name") or "").strip()
        last = (row.get("Last Name") or "").strip()
        if first or last:
            names.append(f"{first} {last}".strip())
    return names


def normalize_name(name):
    name = name.lower()
    name = re.sub(r"[^a-z\s]", "", name)
    return " ".join(name.split())


def matches_connection(authors, connection_names_normalized):
    for author in authors:
        norm = normalize_name(author)
        if not norm:
            continue
        for conn in connection_names_normalized:
            if norm == conn:
                return True
            a_parts = norm.split()
            c_parts = conn.split()
            # tolerate arXiv's "F. Last" vs LinkedIn's "First Last" formatting
            if a_parts and c_parts and a_parts[-1] == c_parts[-1]:
                if a_parts[0][:1] == c_parts[0][:1]:
                    return True
    return False


def matched_keywords(entry, keywords):
    if not keywords:
        return []
    haystack = f"{entry['title']} {entry['summary']}".lower()
    return [k for k in keywords if k.lower() in haystack]


def fetch_and_filter(categories, days, max_results, keywords, connections_path):
    """Run the full fetch -> annotate pipeline. Returns every paper within
    the lookback window (not just keyword/connection matches) -- each is
    tagged with is_connection and matched_keywords so the UI can highlight
    and optionally filter down, but nothing is dropped at this stage. Also
    returns diagnostics (how many entries arXiv actually had available) so
    callers can tell "nothing announced yet" apart from "something's
    broken"."""
    connections = load_connections(connections_path)
    connections_normalized = [normalize_name(n) for n in connections]

    entries, total_available, most_recent_date = fetch_recent_entries(categories, days)
    if max_results and len(entries) > max_results:
        entries = entries[:max_results]

    results = []
    for e in entries:
        e = dict(e)
        e["is_connection"] = matches_connection(e["authors"], connections_normalized)
        e["matched_keywords"] = matched_keywords(e, keywords)
        results.append(e)

    return {
        "papers": results,
        "connections_loaded": len(connections),
        "total_fetched": total_available,
        "within_lookback": len(entries),
        "most_recent_published": most_recent_date.isoformat() if most_recent_date else None,
    }
