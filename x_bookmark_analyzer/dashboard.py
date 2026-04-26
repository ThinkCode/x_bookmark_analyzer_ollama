"""Markdown and HTML output rendering for the bookmark dashboard."""
import json
import re
import time
from collections import Counter
from html import escape

from .config import HTML_OUTPUT, OUTPUT
from .models import bookmark_dt, clean_text

# --- Output helpers ---

def month_key(bookmark: dict) -> str:
    return bookmark_dt(bookmark).strftime("%Y-%m")


def year_key(bookmark: dict) -> str:
    return bookmark_dt(bookmark).strftime("%Y")


def short_excerpt(bookmark: dict, length: int = 220) -> str:
    source = clean_text(bookmark.get("text") or bookmark.get("juice") or "")
    if len(source) <= length:
        return source
    return source[: length - 1].rstrip() + "…"


COMMON_TERMS = {
    "able", "about", "above", "across", "actually", "after", "again", "against", "also",
    "always", "among", "another", "anyone", "anything", "around", "because", "become",
    "becomes", "been", "before", "being", "below", "between", "bookmark", "bookmarks",
    "both", "bring", "came", "cannot", "come", "comes", "coming", "could", "didn",
    "does", "doing", "done", "down", "each", "else", "enough", "even", "ever", "every",
    "everyone", "everything", "find", "first", "from", "full", "gets", "getting", "give",
    "goes", "going", "good", "great", "hadn", "hasn", "have", "haven", "having", "here",
    "hers", "himself", "into", "isn", "itself", "just", "keep", "kind", "know", "last",
    "less", "like", "little", "long", "look", "made", "make", "makes", "many", "might",
    "more", "most", "much", "must", "need", "needs", "never", "next", "nothing", "often",
    "only", "onto", "other", "others", "over", "part", "people", "really", "same",
    "should", "show", "since", "some", "someone", "something", "still", "such", "take",
    "than", "that", "their", "them", "then", "there", "these", "they", "thing", "things",
    "think", "this", "those", "through", "today", "trying", "under", "until", "upon",
    "used", "using", "very", "want", "wants", "wasn", "well", "were", "what", "when",
    "where", "whether", "which", "while", "will", "with", "within", "without", "work",
    "works", "would", "wouldn", "year", "years", "your", "yours", "yourself", "youre",
    "youll", "youve", "https", "http", "www", "com",
    "all", "and", "are", "but", "can", "did", "for", "get", "has", "her", "him", "his",
    "how", "its", "let", "new", "not", "now", "one", "our", "out", "own", "put", "see",
    "she", "the", "too", "two", "use", "was", "way", "who", "why", "you",
}


def build_tag_cloud(bookmarks: list[dict], limit: int = 45) -> list[dict]:
    text = " ".join(
        clean_text(" ".join([
            bookmark.get("text", ""),
            bookmark.get("juice", ""),
            bookmark.get("category", ""),
            bookmark.get("folder_name", ""),
        ]))
        for bookmark in bookmarks
    ).lower()
    words = re.findall(r"[a-z][a-z0-9+-]{2,}", text)
    counts = Counter(word for word in words if word not in COMMON_TERMS and not word.isdigit())
    if not counts:
        return []

    top = counts.most_common(limit)
    max_count = top[0][1]
    min_count = top[-1][1]
    spread = max(max_count - min_count, 1)
    return [
        {
            "term": term,
            "count": count,
            "weight": round(0.85 + ((count - min_count) / spread) * 1.25, 2),
        }
        for term, count in top
    ]


def build_dashboard_data(bookmarks: list[dict]) -> dict:
    sorted_bookmarks = sorted(bookmarks, key=lambda b: b["created_at"], reverse=True)
    month_counts = Counter(month_key(b) for b in sorted_bookmarks)
    year_counts = Counter(year_key(b) for b in sorted_bookmarks)
    category_counts = Counter(b.get("category") or "Uncategorized" for b in sorted_bookmarks)

    month_labels = sorted(month_counts)
    month_series = [{"month": label, "count": month_counts[label]} for label in month_labels]

    years = sorted(year_counts)
    heatmap = []
    for year in years:
        row = {"year": year, "months": []}
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            row["months"].append({"month": month, "count": month_counts.get(key, 0), "key": key})
        heatmap.append(row)

    categories = []
    for category, count in category_counts.most_common():
        categories.append(
            {
                "name": category,
                "count": count,
                "bookmarks": [
                    {
                        "id": b["id"],
                        "author": b["author"],
                        "tweet_url": b["tweet_url"],
                        "resolved_url": b["resolved_urls"][0] if b["resolved_urls"] else "",
                        "text": b["text"],
                        "juice": b.get("juice", ""),
                        "category": b.get("category", "Uncategorized"),
                        "folder_name": b.get("folder_name", ""),
                        "folder_category": b.get("folder_category", ""),
                        "created_at": b["created_at"],
                        "created_label": bookmark_dt(b).strftime("%Y-%m-%d %H:%M UTC"),
                        "excerpt": short_excerpt(b),
                    }
                    for b in sorted_bookmarks
                    if (b.get("category") or "Uncategorized") == category
                ],
            }
        )

    return {
        "total": len(sorted_bookmarks),
        "date_range": {
            "first": bookmark_dt(sorted_bookmarks[-1]).strftime("%Y-%m-%d") if sorted_bookmarks else "",
            "last": bookmark_dt(sorted_bookmarks[0]).strftime("%Y-%m-%d") if sorted_bookmarks else "",
        },
        "top_category": category_counts.most_common(1)[0][0] if category_counts else "",
        "month_series": month_series,
        "heatmap": heatmap,
        "year_counts": [{"year": year, "count": year_counts[year]} for year in years],
        "categories": categories,
        "tag_cloud": build_tag_cloud(sorted_bookmarks),
    }


def markdown_inline(text: str) -> str:
    formatted = escape(text)
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", formatted)
    formatted = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", formatted)
    return formatted


def markdown_to_html(markdown: str) -> str:
    html = []
    list_type = None

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            html.append(f"</{list_type}>")
            list_type = None

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            close_list()
            continue

        if re.fullmatch(r"[-*_]{3,}", line):
            close_list()
            html.append("<hr>")
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 1, 4)
            html.append(f"<h{level}>{markdown_inline(heading.group(2))}</h{level}>")
            continue

        numbered = re.match(r"^\d+\.\s+(.+)$", line)
        if numbered:
            if list_type != "ol":
                close_list()
                html.append("<ol>")
                list_type = "ol"
            html.append(f"<li>{markdown_inline(numbered.group(1))}</li>")
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            if list_type != "ul":
                close_list()
                html.append("<ul>")
                list_type = "ul"
            html.append(f"<li>{markdown_inline(bullet.group(1))}</li>")
            continue

        close_list()
        html.append(f"<p>{markdown_inline(line)}</p>")

    close_list()
    return "\n".join(html)


def render_html(bookmarks: list[dict], analysis: str) -> str:
    data = build_dashboard_data(bookmarks)
    payload = json.dumps(data)
    analysis_html = markdown_to_html(analysis)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>X Bookmark Dashboard</title>
  <style>
    :root {{
      --bg: #f5efe2;
      --panel: rgba(255, 251, 245, 0.84);
      --panel-strong: #fffaf1;
      --ink: #1f241d;
      --muted: #646a61;
      --accent: #c85f38;
      --accent-2: #2f7d6b;
      --border: rgba(31, 36, 29, 0.09);
      --shadow: 0 18px 50px rgba(74, 52, 32, 0.12);
      --control: #ffffff;
      --heat-empty: rgba(47, 125, 107, 0.08);
      --category-text: #1f241d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(200, 95, 56, 0.18), transparent 26rem),
        radial-gradient(circle at top right, rgba(47, 125, 107, 0.18), transparent 30rem),
        linear-gradient(180deg, #f9f1e4 0%, #f1ebdf 100%);
    }}
    body.dark {{
      --bg: #0f1419;
      --panel: rgba(22, 30, 37, 0.92);
      --panel-strong: #18212a;
      --ink: #f0f5f4;
      --muted: #a8b8b2;
      --accent: #7cc7ad;
      --accent-2: #f0a35e;
      --border: rgba(240, 245, 244, 0.14);
      --shadow: 0 20px 55px rgba(0, 0, 0, 0.35);
      --control: #111a21;
      --heat-empty: rgba(124, 199, 173, 0.08);
      --category-text: #f0f5f4;
      background:
        radial-gradient(circle at top left, rgba(124, 199, 173, 0.16), transparent 26rem),
        radial-gradient(circle at top right, rgba(240, 163, 94, 0.12), transparent 30rem),
        var(--bg);
    }}
    a {{ color: inherit; }}
    .shell {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 28px 22px;
      background: color-mix(in srgb, var(--panel-strong) 88%, transparent);
      backdrop-filter: blur(16px);
      border-right: 1px solid var(--border);
      overflow-y: auto;
    }}
    .brand {{
      margin-bottom: 24px;
    }}
    .brand-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .brand h1 {{
      margin: 0;
      font-size: 1.7rem;
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .brand p {{
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .search {{
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 13px 14px;
      background: var(--control);
      color: var(--ink);
      margin: 0 0 18px;
      font: inherit;
    }}
    .theme-toggle {{
      width: 30px;
      height: 30px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 0;
      margin: 0;
      background: linear-gradient(135deg, #fff5c7 0 48%, #18212a 50% 100%);
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      flex: 0 0 auto;
      box-shadow: inset 0 0 0 3px color-mix(in srgb, var(--panel-strong) 75%, transparent);
    }}
    body.dark .theme-toggle {{
      background: linear-gradient(135deg, #7cc7ad 0 48%, #0b1015 50% 100%);
    }}
    .category-list {{
      display: grid;
      gap: 10px;
    }}
    .category-button {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      width: 100%;
      border: 1px solid var(--border);
      background: var(--panel-strong);
      border-radius: 8px;
      padding: 12px 14px;
      cursor: pointer;
      font: inherit;
      color: var(--category-text);
      text-align: left;
      box-shadow: 0 8px 20px rgba(31, 36, 29, 0.04);
    }}
    .category-button.active {{
      border-color: rgba(200, 95, 56, 0.35);
      background: linear-gradient(135deg, rgba(200, 95, 56, 0.14), rgba(47, 125, 107, 0.08));
    }}
    .category-count {{
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .main {{
      padding: 28px;
    }}
    .hero {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 22px;
    }}
    .stat, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}
    .stat .label {{
      color: var(--muted);
      font-size: 0.86rem;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .stat .value {{
      margin-top: 10px;
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .analysis-section {{
      margin-bottom: 18px;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: minmax(420px, 1.4fr) minmax(260px, 0.8fr);
      gap: 18px;
      margin-bottom: 18px;
    }}
    .mini-chart-stack {{
      display: grid;
      gap: 18px;
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 1.1rem;
      letter-spacing: 0;
    }}
    .analysis {{
      color: #2f332d;
      line-height: 1.6;
      font-size: 0.98rem;
    }}
    body.dark .analysis {{ color: var(--ink); }}
    .analysis h2, .analysis h3, .analysis h4 {{
      margin: 1.2rem 0 0.45rem;
      color: var(--ink);
      line-height: 1.25;
    }}
    .analysis h2 {{ font-size: 1.18rem; }}
    .analysis h3 {{ font-size: 1.08rem; }}
    .analysis h4 {{ font-size: 1rem; }}
    .analysis p {{
      margin: 0 0 0.85rem;
      max-width: 82ch;
    }}
    .analysis ol, .analysis ul {{
      display: grid;
      gap: 0.65rem;
      margin: 0.25rem 0 1.1rem 1.35rem;
      padding: 0;
      max-width: 88ch;
    }}
    .analysis li {{
      padding-left: 0.2rem;
    }}
    .analysis strong {{
      color: var(--accent-2);
      font-weight: 800;
    }}
    .analysis em {{
      color: color-mix(in srgb, var(--ink) 80%, var(--accent));
      font-style: italic;
    }}
    .analysis hr {{
      border: 0;
      border-top: 1px solid var(--border);
      margin: 1rem 0;
    }}
    .analysis.collapsed {{
      max-height: 14rem;
      overflow: hidden;
      position: relative;
    }}
    .analysis.collapsed::after {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 4.5rem;
      background: linear-gradient(180deg, transparent, var(--panel));
      pointer-events: none;
    }}
    .analysis-toggle, .load-more, .clear-filter {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--control);
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      padding: 9px 12px;
    }}
    .analysis-toggle {{
      margin-top: 12px;
    }}
    .bars {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(20px, 1fr));
      align-items: end;
      gap: 8px;
      min-height: 120px;
      padding-top: 10px;
    }}
    .bar-wrap {{
      display: flex;
      flex-direction: column;
      justify-content: end;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }}
    .bar {{
      width: 100%;
      min-height: 8px;
      border-radius: 999px 999px 6px 6px;
      background: linear-gradient(180deg, var(--accent), #e7b96b);
    }}
    .bar-label {{
      writing-mode: vertical-rl;
      transform: rotate(180deg);
      font-size: 0.72rem;
      color: var(--muted);
    }}
    .heatmap {{
      display: grid;
      gap: 10px;
    }}
    .tag-cloud {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px 12px;
      align-items: center;
      padding-top: 16px;
      margin-top: 16px;
      border-top: 1px solid var(--border);
    }}
    .tag {{
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--accent);
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      line-height: 1;
      padding: 2px 0;
      text-decoration: none;
      transition: color 140ms ease, transform 140ms ease;
    }}
    .tag:hover, .tag.active {{
      color: var(--accent-2);
      transform: translateY(-1px);
      text-decoration: underline;
      text-underline-offset: 4px;
    }}
    body.dark .tag {{
      color: var(--accent);
    }}
    body.dark .tag:hover, body.dark .tag.active {{
      color: var(--accent-2);
    }}
    .heat-row {{
      display: grid;
      grid-template-columns: 62px repeat(12, minmax(0, 1fr));
      gap: 7px;
      align-items: center;
    }}
    .heat-year {{
      font-size: 0.82rem;
      color: var(--muted);
      font-weight: 600;
    }}
    .heat-cell {{
      aspect-ratio: 1 / 1;
      border-radius: 6px;
      border: 1px solid rgba(31, 36, 29, 0.05);
      display: grid;
      place-items: center;
      font-size: 0.7rem;
      color: rgba(0, 0, 0, 0.55);
      cursor: pointer;
      font: inherit;
    }}
    body.dark .heat-cell {{ color: rgba(255, 255, 255, 0.72); }}
    .heat-cell.active {{
      outline: 2px solid var(--accent-2);
      outline-offset: 2px;
    }}
    .month-head {{
      font-size: 0.7rem;
      color: var(--muted);
      text-align: center;
    }}
    .bookmark-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin: 18px 0;
    }}
    .bookmark-count {{
      color: var(--muted);
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }}
    .card {{
      background: rgba(255, 253, 249, 0.88);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 13px;
      box-shadow: var(--shadow);
    }}
    body.dark .card {{ background: var(--panel); }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 5px 8px;
      background: color-mix(in srgb, var(--accent) 13%, transparent);
      color: var(--ink);
    }}
    .excerpt {{
      margin: 0 0 10px;
      line-height: 1.45;
      font-size: 0.94rem;
    }}
    .summary {{
      margin: 0 0 12px;
      color: #344137;
      line-height: 1.55;
    }}
    .links {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 0.9rem;
      margin-bottom: 12px;
    }}
    .load-more-wrap {{
      display: flex;
      justify-content: center;
      padding-top: 16px;
    }}
    @media (max-width: 1100px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }}
      .hero, .chart-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-row">
          <h1>X Bookmark Atlas</h1>
          <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle dark mode" title="Toggle dark mode"></button>
        </div>
        <p>Browse your saved posts by category, then read the usage patterns hiding underneath.</p>
      </div>
      <input id="search" class="search" type="search" placeholder="Filter categories or bookmarks">
      <div id="category-list" class="category-list"></div>
    </aside>
    <main class="main">
      <section class="hero">
        <div class="stat"><div class="label">Bookmarks</div><div id="stat-total" class="value"></div></div>
        <div class="stat"><div class="label">Date Range</div><div id="stat-range" class="value" style="font-size:1.2rem"></div></div>
        <div class="stat"><div class="label">Top Category</div><div id="stat-category" class="value" style="font-size:1.3rem"></div></div>
        <div class="stat"><div class="label">Categories</div><div id="stat-categories" class="value"></div></div>
      </section>

      <section class="analysis-section">
        <div class="panel">
          <h2>What Your Bookmarks Say</h2>
          <div id="analysis" class="analysis collapsed">{analysis_html}</div>
          <button id="analysis-toggle" class="analysis-toggle" type="button">Show Full Analysis</button>
        </div>
      </section>

      <section class="chart-grid">
        <div class="panel heatmap-panel">
          <h2>Year / Month Heatmap</h2>
          <div id="heatmap" class="heatmap"></div>
          <div id="tag-cloud" class="tag-cloud"></div>
        </div>
        <div class="mini-chart-stack">
          <div class="panel">
            <h2>Bookmarks By Month</h2>
            <div id="month-bars" class="bars"></div>
          </div>
          <div class="panel">
            <h2>Yearly Totals</h2>
            <div id="year-bars" class="bars"></div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="bookmark-toolbar">
          <div>
            <h2 id="current-category" style="margin:0 0 6px">All Categories</h2>
            <div id="bookmark-count" class="bookmark-count"></div>
          </div>
          <button id="clear-filter" class="clear-filter" type="button" hidden>Clear Filters</button>
        </div>
        <div id="cards" class="cards"></div>
        <div class="load-more-wrap">
          <button id="load-more" class="load-more" type="button" hidden>Load More</button>
        </div>
      </section>
    </main>
  </div>

  <script>
    const data = {payload};
    const PAGE_SIZE = 24;
    const state = {{
      category: "All",
      query: "",
      month: "",
      tag: "",
      visible: PAGE_SIZE,
    }};

    const categoryList = document.getElementById("category-list");
    const cards = document.getElementById("cards");
    const search = document.getElementById("search");
    const currentCategory = document.getElementById("current-category");
    const bookmarkCount = document.getElementById("bookmark-count");
    const clearFilter = document.getElementById("clear-filter");
    const loadMore = document.getElementById("load-more");
    const themeToggle = document.getElementById("theme-toggle");
    const analysis = document.getElementById("analysis");
    const analysisToggle = document.getElementById("analysis-toggle");
    const tagCloud = document.getElementById("tag-cloud");

    const statTotal = document.getElementById("stat-total");
    const statRange = document.getElementById("stat-range");
    const statCategory = document.getElementById("stat-category");
    const statCategories = document.getElementById("stat-categories");

    statTotal.textContent = data.total;
    statRange.textContent = `${{data.date_range.first}} → ${{data.date_range.last}}`;
    statCategory.textContent = data.top_category || "—";
    statCategories.textContent = data.categories.length;

    const savedTheme = localStorage.getItem("bookmark-dashboard-theme");
    if (savedTheme === "dark") {{
      document.body.classList.add("dark");
      themeToggle.setAttribute("aria-label", "Switch to light mode");
      themeToggle.setAttribute("title", "Switch to light mode");
    }}

    themeToggle.addEventListener("click", () => {{
      document.body.classList.toggle("dark");
      const isDark = document.body.classList.contains("dark");
      themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
      themeToggle.setAttribute("title", isDark ? "Switch to light mode" : "Switch to dark mode");
      localStorage.setItem("bookmark-dashboard-theme", isDark ? "dark" : "light");
    }});

    analysisToggle.addEventListener("click", () => {{
      analysis.classList.toggle("collapsed");
      analysisToggle.textContent = analysis.classList.contains("collapsed")
        ? "Show Full Analysis"
        : "Show Less";
    }});

    function collapseAnalysis() {{
      analysis.classList.add("collapsed");
      analysisToggle.textContent = "Show Full Analysis";
    }}

    function colorForCount(count, max) {{
      if (!count) return "var(--heat-empty)";
      const ratio = Math.max(0.08, count / Math.max(max, 1));
      return `color-mix(in srgb, var(--accent) ${{Math.round(18 + ratio * 70)}}%, transparent)`;
    }}

    function scrollToCards() {{
      cards.closest(".panel").scrollIntoView({{ behavior: "smooth", block: "start" }});
    }}

    function bookmarkSearchText(bookmark) {{
      return [bookmark.author, bookmark.text, bookmark.juice, bookmark.category, bookmark.folder_name]
        .join(" ")
        .toLowerCase();
    }}

    function ensureCategoryVisible() {{
      if (state.category === "All") return;
      const exists = filteredCategories().some(item => item.name === state.category);
      if (!exists) state.category = "All";
    }}

    function renderBars() {{
      const monthBars = document.getElementById("month-bars");
      const yearBars = document.getElementById("year-bars");
      const maxMonth = Math.max(...data.month_series.map(item => item.count), 1);
      monthBars.innerHTML = data.month_series.map(item => `
        <div class="bar-wrap" title="${{item.month}}: ${{item.count}}">
          <div class="bar" style="height:${{Math.max(10, (item.count / maxMonth) * 92)}}px"></div>
          <div class="bar-label">${{item.month}}</div>
        </div>
      `).join("");

      const maxYear = Math.max(...data.year_counts.map(item => item.count), 1);
      yearBars.innerHTML = data.year_counts.map(item => `
        <div class="bar-wrap" title="${{item.year}}: ${{item.count}}">
          <div class="bar" style="height:${{Math.max(10, (item.count / maxYear) * 92)}}px;background:linear-gradient(180deg,var(--accent-2),var(--accent))"></div>
          <div class="bar-label">${{item.year}}</div>
        </div>
      `).join("");
    }}

    function renderHeatmap() {{
      const heatmap = document.getElementById("heatmap");
      const monthLabels = ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      const max = Math.max(...data.month_series.map(item => item.count), 1);
      const header = `<div class="heat-row">${{monthLabels.map(label => `<div class="month-head">${{label}}</div>`).join("")}}</div>`;
      const rows = data.heatmap.map(row => `
        <div class="heat-row">
          <div class="heat-year">${{row.year}}</div>
          ${{row.months.map(cell => `<button class="heat-cell ${{state.month === cell.key ? "active" : ""}}" type="button" data-month="${{cell.key}}" title="${{cell.key}}: ${{cell.count}}" style="background:${{colorForCount(cell.count, max)}}">${{cell.count || ""}}</button>`).join("")}}
        </div>
      `).join("");
      heatmap.innerHTML = header + rows;
      heatmap.querySelectorAll(".heat-cell").forEach(cell => {{
        cell.addEventListener("click", () => {{
          collapseAnalysis();
          state.month = state.month === cell.dataset.month ? "" : cell.dataset.month;
          state.visible = PAGE_SIZE;
          ensureCategoryVisible();
          renderHeatmap();
          renderTagCloud();
          renderCategories();
          renderCards();
          scrollToCards();
        }});
      }});
    }}

    function renderTagCloud() {{
      tagCloud.innerHTML = data.tag_cloud.map(tag => `
        <button class="tag ${{state.tag === tag.term ? "active" : ""}}" type="button" data-tag="${{tag.term}}" style="font-size:${{tag.weight}}rem" title="${{tag.count}} mentions">${{tag.term}}</button>
      `).join("");
      tagCloud.querySelectorAll(".tag").forEach(tag => {{
        tag.addEventListener("click", () => {{
          collapseAnalysis();
          state.tag = state.tag === tag.dataset.tag ? "" : tag.dataset.tag;
          state.visible = PAGE_SIZE;
          ensureCategoryVisible();
          renderTagCloud();
          renderCategories();
          renderCards();
          scrollToCards();
        }});
      }});
    }}

    function filteredCategories() {{
      const query = state.query.trim().toLowerCase();
      return data.categories
        .map(category => {{
          const bookmarks = category.bookmarks.filter(bookmark =>
            (!state.month || bookmark.created_at.startsWith(state.month)) &&
            (!state.tag || bookmarkSearchText(bookmark).includes(state.tag)) &&
            (!query || bookmarkSearchText(bookmark).includes(query))
          );
          if ((!query || category.name.toLowerCase().includes(query)) && (!state.month || bookmarks.length) && (!state.tag || bookmarks.length)) {{
            return {{ ...category, bookmarks }};
          }}
          if (bookmarks.length) {{
            return {{ ...category, bookmarks }};
          }}
          return null;
        }})
        .filter(Boolean);
    }}

    function renderCategories() {{
      const categories = filteredCategories();
      const allCount = categories.reduce((sum, item) => sum + item.bookmarks.length, 0);
      const buttons = [`
        <button class="category-button ${{state.category === "All" ? "active" : ""}}" data-category="All">
          <span>All Categories</span>
          <span class="category-count">${{allCount}}</span>
        </button>
      `];

      for (const category of categories) {{
        buttons.push(`
          <button class="category-button ${{state.category === category.name ? "active" : ""}}" data-category="${{category.name}}">
            <span>${{category.name}}</span>
            <span class="category-count">${{category.bookmarks.length}}</span>
          </button>
        `);
      }}

      categoryList.innerHTML = buttons.join("");
      categoryList.querySelectorAll(".category-button").forEach(button => {{
        button.addEventListener("click", () => {{
          collapseAnalysis();
          state.category = button.dataset.category;
          state.visible = PAGE_SIZE;
          renderCategories();
          renderCards();
          scrollToCards();
        }});
      }});
    }}

    function currentBookmarks() {{
      const categories = filteredCategories();
      if (state.category === "All") {{
        return categories.flatMap(category => category.bookmarks)
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
      }}
      const category = categories.find(item => item.name === state.category);
      return category ? category.bookmarks : [];
    }}

    function renderCards() {{
      const bookmarks = currentBookmarks();
      currentCategory.textContent = state.category === "All" ? "All Categories" : state.category;
      const monthLabel = state.month ? ` in ${{state.month}}` : "";
      const tagLabel = state.tag ? ` tagged "${{state.tag}}"` : "";
      bookmarkCount.textContent = `${{bookmarks.length}} bookmarks${{monthLabel}}${{tagLabel}}`;
      clearFilter.hidden = !state.month && !state.tag;
      const visibleBookmarks = bookmarks.slice(0, state.visible);
      loadMore.hidden = state.visible >= bookmarks.length;
      loadMore.textContent = `Load More (${{Math.max(bookmarks.length - state.visible, 0)}} remaining)`;

      cards.innerHTML = visibleBookmarks.map(bookmark => `
        <article class="card">
          <div class="meta">
            <span class="pill">${{bookmark.created_label}}</span>
            <span class="pill">@${{bookmark.author || "unknown"}}</span>
            ${{bookmark.folder_name ? `<span class="pill">Folder: ${{bookmark.folder_name}}</span>` : ""}}
          </div>
          <p class="excerpt">${{bookmark.excerpt || ""}}</p>
          <p class="summary">${{bookmark.juice || ""}}</p>
          <div class="links">
            <a href="${{bookmark.tweet_url}}" target="_blank" rel="noreferrer">Open post</a>
            ${{bookmark.resolved_url ? `<a href="${{bookmark.resolved_url}}" target="_blank" rel="noreferrer">Open article</a>` : ""}}
          </div>
        </article>
      `).join("");
    }}

    search.addEventListener("input", event => {{
      collapseAnalysis();
      state.query = event.target.value;
      state.visible = PAGE_SIZE;
      if (state.category !== "All") {{
        ensureCategoryVisible();
      }}
      renderCategories();
      renderCards();
    }});

    clearFilter.addEventListener("click", () => {{
      collapseAnalysis();
      state.month = "";
      state.tag = "";
      state.visible = PAGE_SIZE;
      renderHeatmap();
      renderTagCloud();
      renderCategories();
      renderCards();
    }});

    loadMore.addEventListener("click", () => {{
      collapseAnalysis();
      state.visible += PAGE_SIZE;
      renderCards();
    }});

    renderBars();
    renderHeatmap();
    renderTagCloud();
    renderCategories();
    renderCards();
  </script>
</body>
</html>
"""


def write_markdown(bookmarks: list[dict], analysis: str) -> None:
    out = [
        "# Bookmark Analysis",
        f"_{time.strftime('%Y-%m-%d')} — {len(bookmarks)} bookmarks_\n",
        "## Analysis\n",
        analysis,
        "\n---\n",
        "## Categories\n",
    ]

    for category, count in Counter(b.get("category") or "Uncategorized" for b in bookmarks).most_common():
        out.append(f"- **{category}**: {count}")

    out.append("\n## All Bookmarks\n")
    for bookmark in bookmarks:
        timestamp = bookmark_dt(bookmark).strftime("%Y-%m-%d %H:%M UTC")
        out.append(f"**{timestamp} — @{bookmark['author']} — {bookmark['category']}**")
        if bookmark.get("folder_name"):
            out.append(f"Folder: {bookmark['folder_name']}")
        out.append(bookmark.get("juice") or short_excerpt(bookmark, length=320))
        out.append(f"<{bookmark['tweet_url']}>")
        if bookmark.get("resolved_urls"):
            out.append(f"<{bookmark['resolved_urls'][0]}>")
        out.append(f"> {bookmark['text'][:250]}\n")

    OUTPUT.write_text("\n".join(out))


def read_existing_analysis() -> str:
    if not OUTPUT.exists():
        return ""
    try:
        text = OUTPUT.read_text()
    except Exception:
        return ""

    marker = "## Analysis\n"
    if marker not in text:
        return ""
    analysis = text.split(marker, 1)[1].split("\n---\n", 1)[0].strip()
    return analysis
