#!/usr/bin/env python3
"""
arXiv daily digest (CLI/cron mode): filters quant-ph / cond-mat submissions
by keyword, and always flags papers where an author matches one of your
LinkedIn connections. Writes a static HTML report.

For interactive use, prefer `server.py`, which runs a local web app instead
of regenerating a file each time. This script remains for cron scheduling.

Usage:
    python3 arxiv_scraper.py --keywords keywords.txt --connections connections.csv
    python3 arxiv_scraper.py --keywords "topological,superconductivity,qubit" --days 1

Run with -h for all options. See README.md for setup (getting your LinkedIn
connections export, category codes, cron scheduling).
"""

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

from arxiv_core import DEFAULT_CATEGORIES, load_keywords, fetch_and_filter


def build_html(entries, keywords, connections_loaded, generated_at):
    data = json.dumps(entries, ensure_ascii=False)
    kw_display = html.escape(", ".join(keywords)) if keywords else "(none set)"
    conn_note = (
        f"{connections_loaded} connections loaded"
        if connections_loaded else "no connections file loaded"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>arXiv Daily Digest</title>
<style>
  :root {{
    --bg: #faf9f7; --panel: #fff; --border: #e4e0d8; --text: #22201c;
    --muted: #6b6355; --accent: #a44b2e; --tag-bg: #f1ece2;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    background: var(--bg); color: var(--text);
    margin: 0; padding: 0 1.5rem 4rem;
  }}
  header {{
    max-width: 860px; margin: 0 auto; padding: 2.5rem 0 1.2rem;
    border-bottom: 1px solid var(--border);
  }}
  h1 {{ font-size: 1.8rem; margin: 0 0 .3rem; }}
  .meta {{ color: var(--muted); font-size: .9rem; font-family: -apple-system, sans-serif; }}
  .controls {{
    max-width: 860px; margin: 1.2rem auto; display: flex; gap: .6rem;
    flex-wrap: wrap; font-family: -apple-system, sans-serif;
  }}
  input[type=text] {{
    flex: 1; min-width: 200px; padding: .55rem .8rem; border: 1px solid var(--border);
    border-radius: 6px; font-size: .95rem; background: var(--panel); color: var(--text);
  }}
  label.toggle {{
    display: flex; align-items: center; gap: .4rem; font-size: .9rem;
    color: var(--muted); padding: .55rem .8rem; border: 1px solid var(--border);
    border-radius: 6px; background: var(--panel); cursor: pointer;
  }}
  .count {{ font-family: -apple-system, sans-serif; color: var(--muted); font-size: .85rem;
            max-width: 860px; margin: 0 auto .8rem; }}
  .paper {{
    max-width: 860px; margin: 0 auto 1.1rem; background: var(--panel);
    border: 1px solid var(--border); border-radius: 8px; padding: 1.1rem 1.3rem;
  }}
  .paper.connection {{ border-left: 4px solid var(--accent); }}
  .paper h2 {{ font-size: 1.15rem; margin: 0 0 .35rem; line-height: 1.35; }}
  .paper h2 a {{ color: var(--text); text-decoration: none; }}
  .paper h2 a:hover {{ text-decoration: underline; }}
  .authors {{ color: var(--muted); font-size: .88rem; font-family: -apple-system, sans-serif; margin-bottom: .5rem; }}
  .summary {{ font-size: .95rem; line-height: 1.5; }}
  .tags {{ margin-top: .6rem; display: flex; gap: .4rem; flex-wrap: wrap; }}
  .tag {{
    font-family: -apple-system, sans-serif; font-size: .72rem; padding: .15rem .5rem;
    border-radius: 999px; background: var(--tag-bg); color: var(--muted);
  }}
  .tag.conn-tag {{ background: var(--accent); color: #fff; }}
  .empty {{ text-align: center; color: var(--muted); padding: 3rem 0; font-family: -apple-system, sans-serif; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #1a1815; --panel: #24211d; --border: #3a352c; --text: #ece7dc; --muted: #a39a86; --tag-bg: #322d25; }}
  }}
</style>
</head>
<body>
<header>
  <h1>arXiv Daily Digest</h1>
  <div class="meta">Generated {html.escape(generated_at)} &middot; keywords: {kw_display} &middot; {conn_note}</div>
</header>
<div class="controls">
  <input type="text" id="search" placeholder="Filter by word (title/abstract)...">
  <label class="toggle"><input type="checkbox" id="connOnly"> Connections only</label>
</div>
<div class="count" id="count"></div>
<div id="list"></div>
<div class="empty" id="emptyMsg" style="display:none;">No papers match.</div>

<script>
const PAPERS = {data};

const list = document.getElementById('list');
const search = document.getElementById('search');
const connOnly = document.getElementById('connOnly');
const countEl = document.getElementById('count');
const emptyMsg = document.getElementById('emptyMsg');

function escapeHtml(s) {{
  return s.replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function render() {{
  const q = search.value.trim().toLowerCase();
  const onlyConn = connOnly.checked;
  const filtered = PAPERS.filter(p => {{
    if (onlyConn && !p.is_connection) return false;
    if (!q) return true;
    return (p.title + ' ' + p.summary).toLowerCase().includes(q);
  }});
  countEl.textContent = filtered.length + ' of ' + PAPERS.length + ' papers';
  list.innerHTML = filtered.map(p => `
    <div class="paper ${{p.is_connection ? 'connection' : ''}}">
      <h2><a href="${{p.link}}" target="_blank" rel="noopener">${{escapeHtml(p.title)}}</a></h2>
      <div class="authors">${{escapeHtml(p.authors.join(', '))}}</div>
      <div class="summary">${{escapeHtml(p.summary)}}</div>
      <div class="tags">
        ${{p.is_connection ? '<span class="tag conn-tag">connection</span>' : ''}}
        ${{p.categories.map(c => `<span class="tag">${{escapeHtml(c)}}</span>`).join('')}}
      </div>
    </div>
  `).join('');
  emptyMsg.style.display = filtered.length ? 'none' : 'block';
}}

search.addEventListener('input', render);
connOnly.addEventListener('change', render);
render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Filter daily arXiv submissions by keyword and LinkedIn connections.")
    ap.add_argument("--keywords", help="Comma-separated keywords, or path to a text file (one per line / comma-separated).")
    ap.add_argument("--connections", help="Path to your LinkedIn 'Connections.csv' export.")
    ap.add_argument("--categories", help="Comma-separated arXiv category codes.", default=",".join(DEFAULT_CATEGORIES))
    ap.add_argument("--days", type=int, default=3, help="Include the N most recent arXiv announcement days (default 3; arXiv skips weekends, so 1 can find nothing on a Monday).")
    ap.add_argument("--max-results", type=int, default=2000, help="Cap on how many recent entries to consider per run.")
    ap.add_argument("--output", default="arxiv_report.html", help="Output HTML file path.")
    args = ap.parse_args()

    keywords = load_keywords(args.keywords)
    categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    print(f"Fetching arXiv listings for categories: {', '.join(categories)}", file=sys.stderr)
    result = fetch_and_filter(categories, args.days, args.max_results, keywords, args.connections)
    print(f"{result['connections_loaded']} connections loaded.", file=sys.stderr)
    print(f"{result['total_fetched']} entries available; {result['within_lookback']} within the last {args.days} announcement day(s).", file=sys.stderr)
    if result["total_fetched"] and not result["within_lookback"]:
        print(f"Nothing announced within that window yet -- most recent arXiv announcement day is {result['most_recent_published']}.", file=sys.stderr)
    tagged = sum(1 for p in result["papers"] if p["is_connection"] or p["matched_keywords"])
    print(f"{len(result['papers'])} papers in output; {tagged} flagged as a keyword or connection match.", file=sys.stderr)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_html = build_html(result["papers"], keywords, result["connections_loaded"], generated_at)
    Path(args.output).write_text(out_html, encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
