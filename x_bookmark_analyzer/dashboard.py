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
  <title>X Bookmark Atlas</title>
  <style>
    /* === Tokens === */
    :root {{
      --bg: #f4f6ff;
      --surface: #ffffff;
      --surface-2: rgba(255,255,255,0.75);
      --ink: #0d1117;
      --ink-2: #566070;
      --ink-3: #99a3b3;
      --accent: #5b5ef6;
      --accent-glow: rgba(91,94,246,0.18);
      --accent-2: #0ea571;
      --accent-2-glow: rgba(14,165,113,0.16);
      --warn: #f59e0b;
      --border: rgba(13,17,23,0.07);
      --border-strong: rgba(13,17,23,0.13);
      --shadow-xs: 0 1px 3px rgba(0,0,0,0.04),0 1px 2px rgba(0,0,0,0.03);
      --shadow-sm: 0 2px 8px rgba(91,94,246,0.07),0 1px 3px rgba(0,0,0,0.04);
      --shadow: 0 4px 20px rgba(91,94,246,0.1),0 1px 4px rgba(0,0,0,0.05);
      --radius: 12px;
      --radius-sm: 8px;
      --pill: 999px;
      --sidebar-w: 256px;
      --heat-empty: rgba(91,94,246,0.06);
    }}
    body.dark {{
      --bg: #060912;
      --surface: rgba(12,17,32,0.98);
      --surface-2: rgba(18,26,46,0.8);
      --ink: #dde4f0;
      --ink-2: #7a8ba6;
      --ink-3: #3d4f66;
      --accent: #818cf8;
      --accent-glow: rgba(129,140,248,0.22);
      --accent-2: #34d399;
      --accent-2-glow: rgba(52,211,153,0.18);
      --warn: #fbbf24;
      --border: rgba(255,255,255,0.07);
      --border-strong: rgba(255,255,255,0.13);
      --shadow-xs: 0 1px 3px rgba(0,0,0,0.4);
      --shadow-sm: 0 2px 10px rgba(0,0,0,0.35);
      --shadow: 0 6px 28px rgba(0,0,0,0.5);
      --heat-empty: rgba(129,140,248,0.07);
    }}

    /* === Reset & Base === */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", system-ui, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: var(--ink);
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }}
    body:not(.dark) {{
      background:
        radial-gradient(ellipse 70% 45% at 8% 0%, rgba(91,94,246,0.09) 0%, transparent 55%),
        radial-gradient(ellipse 55% 35% at 92% 5%, rgba(14,165,113,0.07) 0%, transparent 50%),
        var(--bg);
    }}
    body.dark {{
      background:
        radial-gradient(ellipse 65% 40% at 5% 0%, rgba(129,140,248,0.13) 0%, transparent 55%),
        radial-gradient(ellipse 50% 30% at 95% 5%, rgba(52,211,153,0.08) 0%, transparent 50%),
        var(--bg);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; text-underline-offset: 3px; }}

    /* === Layout === */
    .shell {{
      display: grid;
      grid-template-columns: var(--sidebar-w) 1fr;
      min-height: 100vh;
    }}

    /* === Sidebar === */
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
      background: var(--surface);
      border-right: 1px solid var(--border);
      overflow: hidden;
    }}
    .sidebar-body {{
      flex: 1;
      overflow-y: auto;
      padding: 20px 14px 12px;
      scrollbar-width: thin;
      scrollbar-color: var(--border-strong) transparent;
    }}
    .sidebar-footer {{
      padding: 12px 14px;
      border-top: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .footer-wordmark {{
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--ink-3);
      letter-spacing: 0.04em;
    }}

    /* Brand */
    .brand {{ margin-bottom: 18px; }}
    .brand-logo {{
      display: flex;
      align-items: center;
      gap: 9px;
      margin-bottom: 6px;
    }}
    .brand-gem {{
      width: 30px; height: 30px;
      border-radius: 8px;
      background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%);
      display: grid;
      place-items: center;
      flex-shrink: 0;
      box-shadow: 0 2px 8px var(--accent-glow);
    }}
    .brand-title {{
      font-size: 1.05rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1;
      color: var(--ink);
    }}
    .brand-desc {{
      font-size: 0.78rem;
      color: var(--ink-3);
      line-height: 1.45;
    }}

    /* Search */
    .search-wrap {{ position: relative; margin-bottom: 18px; }}
    .search-icon {{
      position: absolute;
      left: 10px; top: 50%;
      transform: translateY(-50%);
      color: var(--ink-3);
      pointer-events: none;
      display: flex;
    }}
    .search {{
      width: 100%;
      background: color-mix(in srgb, var(--ink) 4%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 8px 10px 8px 32px;
      color: var(--ink);
      font: inherit;
      font-size: 0.83rem;
      outline: none;
      transition: border-color 150ms, box-shadow 150ms;
    }}
    .search:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }}
    .search::placeholder {{ color: var(--ink-3); }}

    /* Nav */
    .nav-label {{
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--ink-3);
      margin-bottom: 6px;
      padding: 0 4px;
    }}
    .category-list {{ display: flex; flex-direction: column; gap: 1px; }}
    .category-button {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      width: 100%;
      border: none;
      background: transparent;
      border-radius: var(--radius-sm);
      padding: 7px 10px;
      cursor: pointer;
      font: inherit;
      font-size: 0.83rem;
      color: var(--ink-2);
      text-align: left;
      transition: background 120ms, color 120ms;
      gap: 8px;
    }}
    .category-button:hover {{
      background: color-mix(in srgb, var(--accent) 7%, transparent);
      color: var(--ink);
    }}
    .category-button.active {{
      background: color-mix(in srgb, var(--accent) 11%, transparent);
      color: var(--accent);
      font-weight: 600;
    }}
    .cat-name {{
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
    }}
    .cat-dot {{
      width: 7px; height: 7px;
      border-radius: 50%;
      flex-shrink: 0;
    }}
    .cat-label {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .category-count {{
      font-size: 0.72rem;
      font-weight: 600;
      color: var(--ink-3);
      background: color-mix(in srgb, var(--ink) 6%, transparent);
      border-radius: var(--pill);
      padding: 1px 7px;
      flex-shrink: 0;
    }}
    .category-button.active .category-count {{
      background: color-mix(in srgb, var(--accent) 15%, transparent);
      color: var(--accent);
    }}

    /* Theme toggle */
    .theme-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid var(--border);
      border-radius: var(--pill);
      padding: 4px 10px;
      background: transparent;
      color: var(--ink-2);
      cursor: pointer;
      font: inherit;
      font-size: 0.75rem;
      font-weight: 500;
      transition: background 120ms, color 120ms, border-color 120ms;
    }}
    .theme-toggle:hover {{
      background: color-mix(in srgb, var(--ink) 5%, transparent);
      color: var(--ink);
      border-color: var(--border-strong);
    }}

    /* === Main === */
    .main {{ padding: 18px 24px 52px; }}

    /* Top zone: left 50% metrics stack, right 50% heatmap */
    .top-zone {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-bottom: 8px;
      align-items: stretch;
    }}
    .metrics-stack {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 6px;
    }}
    /* Compact metric card */
    .mcard {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 9px 12px 9px;
      box-shadow: var(--shadow-xs);
      display: flex;
      flex-direction: column;
      gap: 2px;
      overflow: hidden;
      transition: box-shadow 160ms, border-color 160ms;
    }}
    .mcard:hover {{
      box-shadow: var(--shadow-sm);
      border-color: color-mix(in srgb, var(--accent) 22%, transparent);
    }}
    .mcard-lbl {{
      font-size: 0.53rem;
      font-weight: 700;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--ink-3);
      margin-bottom: 1px;
    }}
    .mcard-primary {{
      display: flex;
      align-items: baseline;
      gap: 7px;
      flex-wrap: wrap;
    }}
    .mcard-num {{
      font-size: 1.85rem;
      font-weight: 800;
      letter-spacing: -0.04em;
      line-height: 1;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }}
    .mcard-meta {{
      font-size: 0.6rem;
      font-weight: 600;
      color: var(--ink-3);
      background: color-mix(in srgb, var(--ink) 6%, transparent);
      border-radius: var(--pill);
      padding: 1px 6px;
    }}
    .mcard-sub {{
      font-size: 0.6rem;
      color: var(--ink-3);
    }}
    .mcard-spark {{ line-height: 0; margin-top: auto; padding-top: 4px; }}
    .mcard-spark svg {{ display: block; width: 100%; height: 18px; }}
    /* Trend badge — inline next to number */
    .trend-badge {{
      font-size: 0.6rem;
      font-weight: 700;
      border-radius: var(--pill);
      padding: 1px 6px;
      align-self: center;
    }}
    .trend-up   {{ color: #0ea571; background: color-mix(in srgb, #0ea571 14%, transparent); }}
    .trend-down {{ color: #ef4444; background: color-mix(in srgb, #ef4444 14%, transparent); }}
    /* Categories card: same stat rhythm as month/year, treemap underneath */
    .mcard-cats {{
      display: block;
      flex: 1;
      min-height: 0;
      margin-top: auto;
      padding-top: 4px;
    }}
    .cats-treemap {{
      width: 100%;
      min-height: 36px;
      display: flex;
      align-items: stretch;
      border-radius: 5px;
      overflow: hidden;
    }}
    .cats-treemap svg {{ flex: 1; border-radius: 5px; display: block; }}

    /* Panels */
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow-xs);
    }}
    .panel-hd {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;
    }}
    .panel-hd h2 {{
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--ink-3);
    }}

    /* Analysis strip */
    .analysis-strip {{ margin-bottom: 12px; }}
    .analysis-strip .panel {{
      padding: 12px 18px;
      border-left: 3px solid var(--accent);
    }}
    .analysis-strip-hd {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .strip-icon {{
      flex-shrink: 0;
      width: 18px; height: 18px;
      border-radius: 50%;
      background: color-mix(in srgb, var(--accent) 12%, transparent);
      color: var(--accent);
      display: grid;
      place-items: center;
      font-size: 0.75rem;
      font-weight: 700;
      line-height: 1;
    }}
    .strip-badge {{
      flex-shrink: 0;
      font-size: 0.58rem;
      font-weight: 700;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--accent);
    }}
    .analysis-teaser {{
      flex: 1;
      margin: 0;
      font-size: 0.82rem;
      color: var(--ink-2);
      font-style: italic;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .analysis-show-btn {{
      flex-shrink: 0;
      background: none;
      border: none;
      cursor: pointer;
      font: inherit;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--accent);
      padding: 0;
      white-space: nowrap;
      transition: opacity 120ms;
    }}
    .analysis-show-btn:hover {{ opacity: 0.75; }}
    .analysis-expanded {{
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid var(--border);
    }}
    /* Sidebar section headers */
    .nav-section-hd {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }}
    .nav-section-hd .nav-label {{ margin-bottom: 0; }}
    .sidebar-clear-btn {{
      font-size: 0.65rem;
      font-weight: 600;
      color: var(--accent);
      background: none;
      border: none;
      cursor: pointer;
      font: inherit;
      padding: 0;
      opacity: 0.75;
      transition: opacity 120ms;
    }}
    .sidebar-clear-btn:hover {{ opacity: 1; text-decoration: underline; }}
    /* Tag count inline */
    .tag-count {{
      font-size: 0.7em;
      font-weight: 400;
      opacity: 0.55;
    }}
    /* Analysis content */
    .analysis {{
      color: var(--ink);
      line-height: 1.7;
      font-size: 0.9rem;
    }}
    .analysis h2 {{ font-size: 1rem; font-weight: 700; margin: 1.1rem 0 0.35rem; color: var(--ink); }}
    .analysis h3 {{ font-size: 0.93rem; font-weight: 700; margin: 0.9rem 0 0.3rem; color: var(--ink); }}
    .analysis h4 {{ font-size: 0.87rem; font-weight: 600; margin: 0.75rem 0 0.25rem; color: var(--ink-2); }}
    .analysis p {{ margin: 0 0 0.7rem; max-width: 80ch; }}
    .analysis ol, .analysis ul {{
      margin: 0.2rem 0 0.9rem 1.15rem; padding: 0;
      display: grid; gap: 0.45rem; max-width: 80ch;
    }}
    .analysis strong {{ color: var(--accent-2); font-weight: 700; }}
    .analysis em {{ color: color-mix(in srgb, var(--ink) 70%, var(--accent)); font-style: italic; }}
    .analysis hr {{ border: none; border-top: 1px solid var(--border); margin: 0.9rem 0; }}

    /* Analysis — pull quote + two-column layout */
    .pull-quote {{
      font-size: 1.02rem;
      font-weight: 500;
      line-height: 1.72;
      color: var(--ink);
      padding: 14px 18px 14px 24px;
      margin: 0 0 22px;
      border-left: 3px solid var(--accent);
      background: color-mix(in srgb, var(--accent) 5%, transparent);
      border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
      position: relative;
    }}
    .pull-quote::before {{
      content: '\\201C';
      position: absolute;
      top: -4px; left: 8px;
      font-size: 4.2rem;
      line-height: 1;
      color: var(--accent);
      opacity: 0.16;
      font-family: Georgia, "Times New Roman", serif;
      pointer-events: none;
    }}
    .analysis-cols {{
      column-count: 2;
      column-gap: 38px;
      column-rule: 1px solid var(--border);
      orphans: 4;
      widows: 4;
    }}
    .analysis-cols h2, .analysis-cols h3, .analysis-cols h4 {{
      column-span: all;
      break-after: avoid;
      break-before: avoid;
    }}
    .analysis-cols p {{ max-width: none; break-inside: avoid; }}
    .analysis-cols ol, .analysis-cols ul {{
      max-width: none;
      display: block;
      break-inside: avoid;
    }}
    .analysis-cols li {{ break-inside: avoid; margin-bottom: 0.4rem; }}

    /* Buttons */
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: transparent;
      color: var(--ink-2);
      cursor: pointer;
      font: inherit;
      font-size: 0.8rem;
      font-weight: 500;
      padding: 6px 13px;
      transition: background 120ms, color 120ms, border-color 120ms;
    }}
    .btn:hover {{
      background: color-mix(in srgb, var(--accent) 8%, transparent);
      border-color: color-mix(in srgb, var(--accent) 28%, transparent);
      color: var(--accent);
    }}
    .analysis-toggle {{ margin-top: 12px; }}

    /* Heatmap — right panel inside top-zone */
    .top-heatmap {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 10px 14px 12px;
      box-shadow: var(--shadow-xs);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .top-heatmap .panel-hd {{ margin-bottom: 6px; flex-shrink: 0; }}
    .heatmap {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 3px;
      min-height: 0;
    }}
    .heat-hd {{
      display: grid;
      grid-template-columns: 26px repeat(12, 1fr);
      gap: 3px;
      flex-shrink: 0;
      padding-bottom: 2px;
    }}
    .heat-row {{
      flex: 1;
      display: grid;
      grid-template-columns: 26px repeat(12, 1fr);
      gap: 3px;
      align-items: stretch;
    }}
    .heat-year {{
      font-size: 0.55rem;
      font-weight: 600;
      color: var(--ink-3);
      display: flex;
      align-items: center;
    }}
    .month-head {{ font-size: 0.48rem; color: var(--ink-3); text-align: center; }}
    .heat-cell {{
      border-radius: 3px;
      border: none;
      cursor: pointer;
      transition: transform 110ms, box-shadow 110ms;
      min-height: 0;
    }}
    .heat-cell:hover {{
      transform: scale(1.12);
      box-shadow: 0 2px 8px rgba(0,0,0,0.22);
      z-index: 1;
    }}
    .heat-cell.active {{
      outline: 2px solid var(--accent-2);
      outline-offset: 1px;
    }}

    /* Tag cloud — sidebar */
    .tag-cloud {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px 6px;
      margin-top: 8px;
      align-items: baseline;
    }}
    .tag {{
      appearance: none;
      border: none;
      background: transparent;
      color: var(--accent);
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 0;
      line-height: 1.2;
      transition: color 120ms, transform 120ms;
      opacity: 0.82;
    }}
    .tag:hover {{ color: var(--accent-2); transform: translateY(-1px); opacity: 1; }}
    .tag.active {{ color: var(--accent-2); opacity: 1; }}

    /* Bookmark section */
    .bm-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 12px;
      margin-bottom: 14px;
    }}
    #current-category {{
      font-size: 1.05rem;
      font-weight: 700;
      letter-spacing: -0.025em;
      margin-bottom: 2px;
      color: var(--ink);
    }}
    .bm-count {{ font-size: 0.78rem; color: var(--ink-3); }}

    /* Cards — 3-D flip */
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 14px;
    }}
    /* Perspective shell — fixed height makes every card uniform */
    .card-shell {{ perspective: 1100px; height: 280px; }}
    /* Flipper */
    .card {{
      position: relative;
      transform-style: preserve-3d;
      transition: transform 540ms cubic-bezier(0.4, 0, 0.2, 1);
      height: 100%;
    }}
    @media (hover: hover) {{
      .card-shell:hover .card {{ transform: rotateY(180deg); }}
    }}
    .card.flipped {{ transform: rotateY(180deg); }}
    /* Shared face */
    .card-face {{
      border-radius: var(--radius);
      border: 1px solid var(--border);
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
      overflow: hidden;
      height: 100%;
      box-sizing: border-box;
    }}
    /* Front */
    .card-front {{
      position: relative;
      background: var(--surface);
      display: flex;
      flex-direction: column;
      gap: 9px;
      padding: 14px;
      transition: border-color 150ms, box-shadow 150ms;
    }}
    .card-shell:hover .card-front {{
      border-color: color-mix(in srgb, var(--card-color, var(--accent)) 32%, transparent);
      box-shadow: var(--shadow);
    }}
    .card-front::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; bottom: 0;
      width: 3px;
      border-radius: 12px 0 0 12px;
      background: var(--card-color, var(--accent));
      opacity: 0.55;
    }}
    /* Back — shows the actual X post */
    .card-back {{
      position: absolute;
      inset: 0;
      background: color-mix(in srgb, var(--card-color, var(--accent)) 7%, var(--surface));
      border-color: color-mix(in srgb, var(--card-color, var(--accent)) 26%, transparent);
      transform: rotateY(180deg);
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 14px;
    }}
    .tweet-hd {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .tweet-avatar {{
      width: 30px; height: 30px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      font-size: 0.78rem;
      font-weight: 700;
      color: #fff;
      flex-shrink: 0;
      opacity: 0.88;
    }}
    .x-logo {{ margin-left: auto; flex-shrink: 0; opacity: 0.2; }}
    .tweet-text {{
      font-size: 0.88rem;
      line-height: 1.6;
      color: var(--ink);
      flex: 1;
      overflow-y: auto;
      max-height: 155px;
      scrollbar-width: thin;
      scrollbar-color: var(--border-strong) transparent;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    /* Flip hint on front */
    .flip-cue {{
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 0.67rem;
      color: var(--ink-3);
      opacity: 0.45;
      margin-top: auto;
      padding-top: 4px;
      pointer-events: none;
      user-select: none;
    }}
    /* Shared content styles */
    .card-hd {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
    }}
    .card-author {{ font-weight: 700; font-size: 0.85rem; color: var(--ink); line-height: 1; }}
    .card-author .at {{ font-weight: 400; color: var(--ink-3); }}
    .card-date {{ font-size: 0.72rem; color: var(--ink-3); white-space: nowrap; }}
    .card-body {{
      font-size: 0.855rem;
      line-height: 1.55;
      color: var(--ink);
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
    }}
    .card-juice {{
      font-size: 0.8rem;
      color: var(--ink-2);
      line-height: 1.5;
      font-style: italic;
      padding: 7px 10px;
      background: color-mix(in srgb, var(--accent-2) 7%, transparent);
      border-left: 2px solid var(--accent-2);
      border-radius: 0 6px 6px 0;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
    }}
    .card-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      border-radius: var(--pill);
      padding: 2px 8px;
      font-size: 0.71rem;
      font-weight: 500;
      background: color-mix(in srgb, var(--card-color, var(--accent)) 10%, transparent);
      color: var(--card-color, var(--accent));
    }}
    .pill.folder {{
      background: color-mix(in srgb, var(--warn) 10%, transparent);
      color: color-mix(in srgb, var(--warn) 75%, var(--ink));
    }}
    .card-links {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .card-link {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--accent);
      padding: 4px 10px;
      border-radius: var(--radius-sm);
      border: 1px solid color-mix(in srgb, var(--accent) 22%, transparent);
      transition: background 120ms, color 120ms, border-color 120ms;
    }}
    .card-link:hover {{
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      text-decoration: none;
    }}
    .card-link.sec {{ color: var(--ink-2); border-color: var(--border); }}
    .card-link.sec:hover {{
      background: color-mix(in srgb, var(--ink) 7%, transparent);
      color: var(--ink);
      border-color: var(--border-strong);
    }}

    .load-more-wrap {{ display: flex; justify-content: center; padding-top: 20px; }}

    /* Responsive */
    @media (max-width: 1100px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; height: auto; border-right: none; border-bottom: 1px solid var(--border); }}
      .sidebar-body {{ max-height: 55vh; }}
      .top-zone {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 600px) {{
      .top-zone {{ grid-template-columns: 1fr; }}
      .main {{ padding: 14px; }}
    }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: var(--border-strong); border-radius: 99px; }}

    /* Fade-in */
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .stat {{ animation: fadeUp 280ms ease both; }}
    .stat:nth-child(1) {{ animation-delay: 30ms; }}
    .stat:nth-child(2) {{ animation-delay: 70ms; }}
    .stat:nth-child(3) {{ animation-delay: 110ms; }}
    .stat:nth-child(4) {{ animation-delay: 150ms; }}
    .panel {{ animation: fadeUp 320ms ease 160ms both; }}
  </style>
</head>
<body>
  <div class="shell">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-body">
        <div class="brand">
          <div class="brand-logo">
            <div class="brand-gem">
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                <path d="M3 2.5A1.5 1.5 0 0 1 4.5 1h7A1.5 1.5 0 0 1 13 2.5v10.086a1 1 0 0 1-1.707.707L8 10l-3.293 3.293A1 1 0 0 1 3 12.586V2.5z" fill="white"/>
              </svg>
            </div>
            <span class="brand-title">Bookmark Atlas</span>
          </div>
          <p class="brand-desc">Navigate your saved posts by topic, timeline &amp; theme.</p>
        </div>

        <div class="search-wrap">
          <span class="search-icon">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <circle cx="6.5" cy="6.5" r="5" stroke="currentColor" stroke-width="1.6"/>
              <path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
            </svg>
          </span>
          <input id="search" class="search" type="search" placeholder="Search bookmarks&hellip;">
        </div>

        <div class="nav-section-hd">
          <p class="nav-label">Categories</p>
          <button id="sidebar-clear" class="sidebar-clear-btn" type="button" hidden>&#x2715; clear</button>
        </div>
        <div id="category-list" class="category-list"></div>

        <p class="nav-label" style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border)">Top Tags</p>
        <div id="tag-cloud" class="tag-cloud"></div>
      </div>

      <div class="sidebar-footer">
        <span class="footer-wordmark">X ATLAS</span>
        <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Toggle dark mode">
          <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
            <path id="theme-icon" d="M8 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0-10a1 1 0 0 0 1-1V1a1 1 0 1 0-2 0v.5A1 1 0 0 0 8 2zm0 12a1 1 0 0 0-1 1v.5a1 1 0 1 0 2 0V15a1 1 0 0 0-1-1zm7-7h-.5a1 1 0 1 0 0 2H15a1 1 0 1 0 0-2zM2 8a1 1 0 0 0-1-1H.5a1 1 0 1 0 0 2H1a1 1 0 0 0 1-1zm10.95-3.536.354-.354a1 1 0 0 0-1.414-1.414l-.354.354a1 1 0 0 0 1.414 1.414zm-9.9 7.072-.354.354a1 1 0 0 0 1.414 1.414l.354-.354a1 1 0 0 0-1.414-1.414zm9.9.354.354.354a1 1 0 0 0 1.414-1.414l-.354-.354a1 1 0 0 0-1.414 1.414zm-9.9-7.072-.354-.354a1 1 0 0 0-1.414 1.414l.354.354a1 1 0 0 0 1.414-1.414z"/>
          </svg>
          <span id="theme-label">Light</span>
        </button>
      </div>
    </aside>

    <!-- Main -->
    <main class="main">
      <!-- Top zone: left 50% = 3 metric cards, right 50% = heatmap -->
      <div class="top-zone">
        <div class="metrics-stack">
          <!-- Month metric -->
          <div class="mcard">
            <div class="mcard-lbl">Bookmarks / Month</div>
            <div class="mcard-primary">
              <span id="stat-month-count" class="mcard-num"></span>
              <span id="month-trend" class="trend-badge"></span>
              <span id="stat-month-label" class="mcard-sub"></span>
            </div>
            <div id="month-spark" class="mcard-spark"></div>
          </div>
          <!-- Year metric -->
          <div class="mcard">
            <div class="mcard-lbl">Bookmarks / Year</div>
            <div class="mcard-primary">
              <span id="stat-year-count" class="mcard-num"></span>
              <span id="year-span-lbl" class="mcard-meta"></span>
              <span id="stat-year-label" class="mcard-sub"></span>
            </div>
            <div id="year-spark" class="mcard-spark"></div>
          </div>
          <!-- Categories + treemap -->
          <div class="mcard">
            <div class="mcard-lbl">Categories <span id="stat-categories" class="mcard-meta" style="margin-left:3px"></span></div>
            <div class="mcard-primary">
              <span id="stat-total" class="mcard-num"></span>
              <span class="mcard-sub">total bookmarks</span>
            </div>
            <div class="mcard-cats">
              <div id="categories-treemap" class="cats-treemap"></div>
            </div>
          </div>
        </div>
        <!-- Right: Activity Heatmap -->
        <div class="top-heatmap">
          <div class="panel-hd"><h2>Activity Heatmap</h2></div>
          <div id="heatmap" class="heatmap"></div>
        </div>
      </div>

      <!-- Analysis thin strip -->
      <section class="analysis-strip">
        <div class="panel">
          <div class="analysis-strip-hd">
            <span class="strip-icon">+</span>
            <span class="strip-badge">AI Analysis</span>
            <p id="analysis-teaser" class="analysis-teaser"></p>
            <button id="analysis-toggle" class="analysis-show-btn" type="button">Show full analysis &#x2192;</button>
          </div>
          <div id="analysis-expanded" class="analysis-expanded" hidden>
            <div id="analysis" class="analysis">{analysis_html}</div>
          </div>
        </div>
      </section>

      <!-- Cards — front and center -->
      <section class="panel">
        <div class="bm-toolbar">
          <div>
            <div id="current-category">All Categories</div>
            <div id="bookmark-count" class="bm-count"></div>
          </div>
          <button id="clear-filter" class="btn" type="button" hidden>&#x2715;&nbsp;Clear Filters</button>
        </div>
        <div id="cards" class="cards"></div>
        <div class="load-more-wrap">
          <button id="load-more" class="btn" type="button" hidden>Load More</button>
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

    const PALETTE = [
      "#6366f1","#0ea571","#f59e0b","#ef4444",
      "#8b5cf6","#06b6d4","#f97316","#84cc16",
      "#ec4899","#14b8a6","#a855f7","#3b82f6",
    ];
    const catColorMap = {{}};
    data.categories.forEach((cat, i) => {{ catColorMap[cat.name] = PALETTE[i % PALETTE.length]; }});

    const categoryList = document.getElementById("category-list");
    const cards = document.getElementById("cards");
    const search = document.getElementById("search");
    const currentCategory = document.getElementById("current-category");
    const bookmarkCount = document.getElementById("bookmark-count");
    const clearFilter = document.getElementById("clear-filter");
    const loadMore = document.getElementById("load-more");
    const themeToggle = document.getElementById("theme-toggle");
    const themeLabel = document.getElementById("theme-label");
    const themeIcon = document.getElementById("theme-icon");
    const analysis = document.getElementById("analysis");
    const analysisExpanded = document.getElementById("analysis-expanded");
    const analysisToggle = document.getElementById("analysis-toggle");
    const tagCloud = document.getElementById("tag-cloud");

    document.getElementById("stat-total").textContent = data.total;

    const moonPath = "M8 3a5 5 0 1 0 4.03 7.97A5.5 5.5 0 0 1 5 7.5 5.5 5.5 0 0 1 8 3z";
    const sunPath = "M8 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0-10a1 1 0 0 0 1-1V1a1 1 0 1 0-2 0v.5A1 1 0 0 0 8 2zm0 12a1 1 0 0 0-1 1v.5a1 1 0 1 0 2 0V15a1 1 0 0 0-1-1zm7-7h-.5a1 1 0 1 0 0 2H15a1 1 0 1 0 0-2zM2 8a1 1 0 0 0-1-1H.5a1 1 0 1 0 0 2H1a1 1 0 0 0 1-1zm10.95-3.536.354-.354a1 1 0 0 0-1.414-1.414l-.354.354a1 1 0 0 0 1.414 1.414zm-9.9 7.072-.354.354a1 1 0 0 0 1.414 1.414l.354-.354a1 1 0 0 0-1.414-1.414zm9.9.354.354.354a1 1 0 0 0 1.414-1.414l-.354-.354a1 1 0 0 0-1.414 1.414zm-9.9-7.072-.354-.354a1 1 0 0 0-1.414 1.414l.354.354a1 1 0 0 0 1.414-1.414z";

    function applyTheme(dark) {{
      document.body.classList.toggle("dark", dark);
      themeLabel.textContent = dark ? "Dark" : "Light";
      themeIcon.setAttribute("d", dark ? moonPath : sunPath);
      themeToggle.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    }}

    const savedTheme = localStorage.getItem("bm-theme");
    applyTheme(savedTheme === "dark");

    themeToggle.addEventListener("click", () => {{
      const isDark = !document.body.classList.contains("dark");
      applyTheme(isDark);
      localStorage.setItem("bm-theme", isDark ? "dark" : "light");
    }});

    analysisToggle.addEventListener("click", () => {{
      const expanded = analysisExpanded.hidden;
      analysisExpanded.hidden = !expanded;
      analysisToggle.textContent = expanded ? "Collapse" : "Show Analysis";
    }});

    function collapseAnalysis() {{
      if (analysisExpanded) analysisExpanded.hidden = true;
      if (analysisToggle) analysisToggle.textContent = "Show Analysis";
    }}

    function colorForCount(count, max) {{
      if (!count) return "var(--heat-empty)";
      const ratio = Math.max(0.08, count / Math.max(max, 1));
      return `color-mix(in srgb, var(--accent) ${{Math.round(16 + ratio * 72)}}%, transparent)`;
    }}

    function scrollToCards() {{
      cards.closest(".panel").scrollIntoView({{ behavior: "smooth", block: "start" }});
    }}

    function bookmarkSearchText(b) {{
      return [b.author, b.text, b.juice, b.category, b.folder_name].join(" ").toLowerCase();
    }}

    function ensureCategoryVisible() {{
      if (state.category === "All") return;
      if (!filteredCategories().some(c => c.name === state.category)) state.category = "All";
    }}

    /* SVG sparkline line/area chart */
    function makeLineSparkline(values, color, filled) {{
      if (!values || !values.length) return "";
      const w = 300, h = 56;
      const max = Math.max(...values, 1);
      const n = values.length;
      const pts = values.map((v, i) => [
        n === 1 ? w / 2 : (i / (n - 1)) * w,
        h - Math.max(3, (v / max) * (h - 6))
      ]);
      const pathD = pts.map((p, i) => `${{i ? "L" : "M"}}${{p[0].toFixed(1)}} ${{p[1].toFixed(1)}}`).join(" ");
      const areaD = `${{pathD}} L${{w}} ${{h}} L0 ${{h}} Z`;
      const dot = pts[pts.length - 1];
      return `<svg viewBox="0 0 ${{w}} ${{h}}" preserveAspectRatio="none" style="overflow:visible">
        ${{filled ? `<defs><linearGradient id="sg${{color.replace(/[^a-z0-9]/gi,"")}}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${{color}}" stop-opacity="0.18"/><stop offset="100%" stop-color="${{color}}" stop-opacity="0"/></linearGradient></defs><path d="${{areaD}}" fill="url(#sg${{color.replace(/[^a-z0-9]/gi,"")}})" />` : ""}}
        <path d="${{pathD}}" fill="none" stroke="${{color}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="${{dot[0].toFixed(1)}}" cy="${{dot[1].toFixed(1)}}" r="3" fill="${{color}}"/>
      </svg>`;
    }}

    /* SVG treemap for categories */
    function makeTreemap(cats, vw, vh) {{
      if (!cats || !cats.length) return "";
      const top = cats.slice(0, 11);
      const total = top.reduce((s, c) => s + (c.count || 0), 0);
      if (!total) return "";
      function tmSlice(items, x, y, w, h) {{
        if (!items.length) return [];
        if (items.length === 1) return [{{ ...items[0], x, y, w, h }}];
        const itemTot = items.reduce((s, c) => s + (c.count || 0), 0);
        let acc = 0, split = 1;
        for (let i = 0; i < items.length - 1; i++) {{
          acc += items[i].count || 0;
          split = i + 1;
          if (acc / itemTot >= 0.5) break;
        }}
        const r = items.slice(0, split).reduce((s, c) => s + (c.count || 0), 0) / itemTot;
        if (w >= h) {{
          return [
            ...tmSlice(items.slice(0, split), x, y, w * r, h),
            ...tmSlice(items.slice(split), x + w * r, y, w * (1 - r), h),
          ];
        }} else {{
          return [
            ...tmSlice(items.slice(0, split), x, y, w, h * r),
            ...tmSlice(items.slice(split), x, y + h * r, w, h * (1 - r)),
          ];
        }}
      }}
      const rects = tmSlice(top, 0, 0, vw, vh);
      const GAP = 2;
      const parts = [];
      rects.forEach((rect, i) => {{
        const gx = rect.x + GAP / 2, gy = rect.y + GAP / 2;
        const gw = Math.max(0, rect.w - GAP), gh = Math.max(0, rect.h - GAP);
        if (gw <= 0 || gh <= 0) return;
        const fill = PALETTE[i % PALETTE.length];
        parts.push(`<rect x="${{gx.toFixed(1)}}" y="${{gy.toFixed(1)}}" width="${{gw.toFixed(1)}}" height="${{gh.toFixed(1)}}" fill="${{fill}}" rx="3"><title>${{rect.name}}: ${{rect.count}}</title></rect>`);
      }});
      return `<svg viewBox="0 0 ${{vw}} ${{vh}}" preserveAspectRatio="none" style="display:block;width:100%;height:100%">${{parts.join("")}}</svg>`;
    }}

    function renderHeroCards() {{
      const months = data.month_series;
      const lastM = months[months.length - 1] || {{}};
      const prevM = months[months.length - 2] || {{}};
      const mCount = lastM.count || 0;
      const pCount = prevM.count || 0;

      document.getElementById("stat-month-count").textContent = mCount;
      document.getElementById("stat-month-label").textContent = lastM.month || "";
      document.getElementById("month-spark").innerHTML = makeLineSparkline(months.map(d => d.count), "var(--accent)", true);

      const trendEl = document.getElementById("month-trend");
      if (pCount > 0) {{
        const pct = Math.round((mCount - pCount) / pCount * 100);
        trendEl.textContent = `${{pct >= 0 ? "+" : ""}}${{pct}}%`;
        trendEl.className = `trend-badge ${{pct >= 0 ? "trend-up" : "trend-down"}}`;
      }}

      const years = data.year_counts;
      const curYear = String(new Date().getFullYear());
      const curYearData = years.find(y => y.year === curYear) || years[years.length - 1] || {{}};
      document.getElementById("stat-year-count").textContent = curYearData.count || 0;
      document.getElementById("stat-year-label").textContent = curYearData.year || "";
      document.getElementById("year-span-lbl").textContent = `${{years.length}} yr${{years.length !== 1 ? "s" : ""}}`;
      document.getElementById("year-spark").innerHTML = makeLineSparkline(years.map(d => d.count), "var(--accent-2)", true);

      document.getElementById("stat-total").textContent = data.total;
      document.getElementById("stat-categories").textContent = data.categories.length;

      /* Treemap — rendered after layout so dimensions are available */
      requestAnimationFrame(() => {{
        const tmEl = document.getElementById("categories-treemap");
        if (tmEl) {{
          const vw = Math.max(tmEl.clientWidth || 160, 80);
          const vh = Math.max(tmEl.clientHeight || 48, 36);
          tmEl.innerHTML = makeTreemap(data.categories, vw, vh);
        }}
      }});
    }}

    function renderBars() {{}} /* bars replaced by stat card sparklines */

    function renderHeatmap() {{
      const heatmap = document.getElementById("heatmap");
      const monthLabels = ["","J","F","M","A","M","J","J","A","S","O","N","D"];
      const max = Math.max(...data.month_series.map(d => d.count), 1);
      const header = `<div class="heat-hd">${{monthLabels.map(l => `<div class="month-head">${{l}}</div>`).join("")}}</div>`;
      const rows = data.heatmap.map(row => `
        <div class="heat-row">
          <div class="heat-year">${{row.year}}</div>
          ${{row.months.map(cell => `<button class="heat-cell ${{state.month === cell.key ? "active" : ""}}" type="button" data-month="${{cell.key}}" title="${{cell.key}}: ${{cell.count}}" style="background:${{colorForCount(cell.count,max)}}"></button>`).join("")}}
        </div>
      `).join("");
      heatmap.innerHTML = header + rows;
      heatmap.querySelectorAll(".heat-cell").forEach(cell => {{
        cell.addEventListener("click", () => {{
          collapseAnalysis();
          state.month = state.month === cell.dataset.month ? "" : cell.dataset.month;
          state.visible = PAGE_SIZE;
          ensureCategoryVisible();
          renderHeatmap(); renderTagCloud(); renderCategories(); renderCards();
          scrollToCards();
        }});
      }});
    }}

    function renderTagCloud() {{
      const topTags = data.tag_cloud.slice(0, 18);
      tagCloud.innerHTML = topTags.map(tag => `
        <button class="tag ${{state.tag === tag.term ? "active" : ""}}" type="button" data-tag="${{tag.term}}" style="font-size:${{Math.min(tag.weight, 0.88)}}rem" title="${{tag.count}} mentions">${{tag.term}} <span class="tag-count">${{tag.count}}</span></button>
      `).join("");
      tagCloud.querySelectorAll(".tag").forEach(tag => {{
        tag.addEventListener("click", () => {{
          collapseAnalysis();
          state.tag = state.tag === tag.dataset.tag ? "" : tag.dataset.tag;
          state.visible = PAGE_SIZE;
          ensureCategoryVisible();
          renderTagCloud(); renderCategories(); renderCards();
          scrollToCards();
        }});
      }});
    }}

    function filteredCategories() {{
      const query = state.query.trim().toLowerCase();
      return data.categories.map(cat => {{
        const bookmarks = cat.bookmarks.filter(b =>
          (!state.month || b.created_at.startsWith(state.month)) &&
          (!state.tag || bookmarkSearchText(b).includes(state.tag)) &&
          (!query || bookmarkSearchText(b).includes(query))
        );
        if ((!query || cat.name.toLowerCase().includes(query)) && (!state.month || bookmarks.length) && (!state.tag || bookmarks.length))
          return {{ ...cat, bookmarks }};
        if (bookmarks.length) return {{ ...cat, bookmarks }};
        return null;
      }}).filter(Boolean);
    }}

    function renderCategories() {{
      const cats = filteredCategories();
      const allCount = cats.reduce((s, c) => s + c.bookmarks.length, 0);
      const buttons = [`
        <button class="category-button ${{state.category === "All" ? "active" : ""}}" data-category="All">
          <span class="cat-name">
            <span class="cat-dot" style="background:linear-gradient(135deg,var(--accent),var(--accent-2))"></span>
            <span class="cat-label">All Categories</span>
          </span>
          <span class="category-count">${{allCount}}</span>
        </button>
      `];
      cats.forEach(cat => {{
        const color = catColorMap[cat.name] || "var(--accent)";
        buttons.push(`
          <button class="category-button ${{state.category === cat.name ? "active" : ""}}" data-category="${{cat.name}}">
            <span class="cat-name">
              <span class="cat-dot" style="background:${{color}}"></span>
              <span class="cat-label">${{cat.name}}</span>
            </span>
            <span class="category-count">${{cat.bookmarks.length}}</span>
          </button>
        `);
      }});
      categoryList.innerHTML = buttons.join("");
      categoryList.querySelectorAll(".category-button").forEach(btn => {{
        btn.addEventListener("click", () => {{
          collapseAnalysis();
          state.category = btn.dataset.category;
          state.visible = PAGE_SIZE;
          renderCategories(); renderCards();
          scrollToCards();
        }});
      }});
      const sidebarClear = document.getElementById("sidebar-clear");
      if (sidebarClear) sidebarClear.hidden = state.category === "All" && !state.tag;
    }}

    function currentBookmarks() {{
      const cats = filteredCategories();
      if (state.category === "All")
        return cats.flatMap(c => c.bookmarks).sort((a,b) => b.created_at.localeCompare(a.created_at));
      const cat = cats.find(c => c.name === state.category);
      return cat ? cat.bookmarks : [];
    }}

    function escapeHtml(s) {{
      return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }}

    function renderCards() {{
      const bookmarks = currentBookmarks();
      currentCategory.textContent = state.category === "All" ? "All Categories" : state.category;
      const monthLabel = state.month ? ` · ${{state.month}}` : "";
      const tagLabel = state.tag ? ` · "${{state.tag}}"` : "";
      bookmarkCount.textContent = `${{bookmarks.length}} bookmarks${{monthLabel}}${{tagLabel}}`;
      clearFilter.hidden = !state.month && !state.tag;
      const visible = bookmarks.slice(0, state.visible);
      loadMore.hidden = state.visible >= bookmarks.length;
      loadMore.textContent = `Load More (${{Math.max(bookmarks.length - state.visible, 0)}} remaining)`;

      cards.innerHTML = visible.map(b => {{
        const color = catColorMap[b.category] || "var(--accent)";
        const dateShort = b.created_label ? b.created_label.slice(0, 10) : "";
        const initials = (b.author || "?").slice(0, 2).toUpperCase();
        return `
          <div class="card-shell" style="--card-color:${{color}}">
            <div class="card">
              <!-- Front: summary view -->
              <div class="card-face card-front">
                <div class="card-hd">
                  <div class="card-author"><span class="at">@</span>${{b.author || "unknown"}}</div>
                  <div class="card-date">${{dateShort}}</div>
                </div>
                ${{b.excerpt ? `<div class="card-body">${{b.excerpt}}</div>` : ""}}
                ${{b.juice ? `<div class="card-juice">${{b.juice}}</div>` : ""}}
                <div class="card-tags">
                  <span class="pill">${{b.category || "Uncategorized"}}</span>
                  ${{b.folder_name ? `<span class="pill folder">${{b.folder_name}}</span>` : ""}}
                </div>
                <div class="card-links">
                  <a class="card-link" href="${{b.tweet_url}}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">
                    Open post ↗
                  </a>
                  ${{b.resolved_url ? `<a class="card-link sec" href="${{b.resolved_url}}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">Article</a>` : ""}}
                </div>
                <div class="flip-cue">
                  <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor"><path d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36a.25.25 0 0 1 .192-.41zm-11 2h3.932a.25.25 0 0 0 .192-.41L2.692 6.23a.25.25 0 0 0-.384 0L.342 8.59A.25.25 0 0 0 .534 9z"/><path fill-rule="evenodd" d="M8 3c-1.552 0-2.94.707-3.857 1.818a.5.5 0 1 1-.771-.636A6.002 6.002 0 0 1 13.917 7H12.9A5.002 5.002 0 0 0 8 3zM3.1 9a5.002 5.002 0 0 0 8.757 2.182.5.5 0 1 1 .771.636A6.002 6.002 0 0 1 2.083 9H3.1z"/></svg>
                  hover to see post
                </div>
              </div>
              <!-- Back: raw X post -->
              <div class="card-face card-back">
                <div class="tweet-hd">
                  <div class="tweet-avatar" style="background:${{color}}">${{initials}}</div>
                  <div>
                    <div class="card-author"><span class="at">@</span>${{b.author || "unknown"}}</div>
                    <div class="card-date">${{dateShort}}</div>
                  </div>
                  <svg class="x-logo" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.73-8.835L1.254 2.25H8.08l4.253 5.622 5.91-5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                </div>
                <div class="tweet-text">${{escapeHtml(b.text)}}</div>
                <div class="card-links" style="margin-top:auto">
                  <a class="card-link" href="${{b.tweet_url}}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">Open on X ↗</a>
                  ${{b.resolved_url ? `<a class="card-link sec" href="${{b.resolved_url}}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">Article</a>` : ""}}
                </div>
              </div>
            </div>
          </div>
        `;
      }}).join("");

      /* Touch: click anywhere on shell toggles flip */
      if (window.matchMedia("(hover: none)").matches) {{
        cards.querySelectorAll(".card-shell").forEach(shell => {{
          shell.addEventListener("click", () => {{
            shell.querySelector(".card").classList.toggle("flipped");
          }});
        }});
      }}
    }}

    search.addEventListener("input", e => {{
      collapseAnalysis();
      state.query = e.target.value;
      state.visible = PAGE_SIZE;
      if (state.category !== "All") ensureCategoryVisible();
      renderCategories(); renderCards();
    }});

    clearFilter.addEventListener("click", () => {{
      collapseAnalysis();
      state.month = ""; state.tag = "";
      state.visible = PAGE_SIZE;
      renderHeatmap(); renderTagCloud(); renderCategories(); renderCards();
    }});

    const sidebarClearBtn = document.getElementById("sidebar-clear");
    if (sidebarClearBtn) {{
      sidebarClearBtn.addEventListener("click", () => {{
        state.category = "All";
        state.tag = "";
        state.visible = PAGE_SIZE;
        renderTagCloud(); renderCategories(); renderCards();
      }});
    }}

    loadMore.addEventListener("click", () => {{
      collapseAnalysis();
      state.visible += PAGE_SIZE;
      renderCards();
    }});

    function reformatAnalysis() {{
      const el = document.getElementById("analysis");
      if (!el || !el.children.length) return;
      /* Populate teaser from first paragraph */
      const firstP = el.querySelector("p, li");
      const teaser = document.getElementById("analysis-teaser");
      if (firstP && teaser) {{
        const txt = firstP.textContent.trim();
        teaser.textContent = txt.length > 180 ? txt.slice(0, 180) + "..." : txt;
      }}
      /* Promote first paragraph to pull-quote */
      const firstBlock = el.querySelector("p");
      if (firstBlock) {{
        const quote = document.createElement("blockquote");
        quote.className = "pull-quote";
        quote.innerHTML = firstBlock.innerHTML;
        firstBlock.replaceWith(quote);
      }}
      /* Wrap remaining content in two-column layout */
      const rest = Array.from(el.children).filter(c => c.tagName !== "BLOCKQUOTE");
      if (rest.length > 0) {{
        const cols = document.createElement("div");
        cols.className = "analysis-cols";
        rest.forEach(c => cols.appendChild(c));
        el.appendChild(cols);
      }}
    }}

    renderHeroCards();
    renderBars();
    renderHeatmap();
    renderTagCloud();
    renderCategories();
    renderCards();
    reformatAnalysis();
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
