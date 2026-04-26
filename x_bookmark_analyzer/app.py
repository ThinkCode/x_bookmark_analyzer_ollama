"""Command-line orchestration for the bookmark analyzer."""

from .config import FORCE_REBUILD_CATEGORIES, HTML_OUTPUT, OUTPUT, STOP_ON_FIRST_STALE_FOLDER
from .dashboard import read_existing_analysis, render_html, write_markdown
from .enrichment import enrich
from .llm import analyze, categorize_all, read_obsidian, summarize_all
from .models import (
    apply_checkpoint,
    apply_summary_checkpoint,
    hydrate_bookmarks,
    load_existing_bookmarks,
    merge_bookmarks,
    reset_categories,
    save_cache,
    save_checkpoint,
)
from .scraper import scrape_bookmarks

# --- Main ---

def main() -> None:
    existing = load_existing_bookmarks()
    if FORCE_REBUILD_CATEGORIES and existing:
        existing = apply_summary_checkpoint(existing)
        existing = reset_categories(existing)
        save_cache(existing)
        save_checkpoint(existing)
    else:
        existing = apply_checkpoint(existing)

    if existing:
        missing_folder_metadata = sum(1 for bookmark in existing if not bookmark.get("folder_name"))
        if missing_folder_metadata:
            print(f"Backfilling folder metadata for {missing_folder_metadata} cached bookmarks.")
        print("Attempting to fetch only new bookmarks since the last run...")
        new_bookmarks = scrape_bookmarks(
            {b["id"] for b in existing},
            allow_failure=True,
            stop_on_first_stale_folder=STOP_ON_FIRST_STALE_FOLDER and missing_folder_metadata == 0,
            existing_bookmarks=existing,
        )
    else:
        new_bookmarks = scrape_bookmarks()

    new_bookmarks = hydrate_bookmarks(new_bookmarks)
    bookmarks = merge_bookmarks(existing, new_bookmarks)
    save_cache(bookmarks)
    save_checkpoint(bookmarks)

    bookmarks = enrich(bookmarks)
    bookmarks = summarize_all(bookmarks)
    bookmarks = categorize_all(bookmarks)
    bookmarks = hydrate_bookmarks(bookmarks)
    save_cache(bookmarks)
    save_checkpoint(bookmarks)

    existing_analysis = read_existing_analysis()
    if not new_bookmarks and existing_analysis:
        print("\nNo new bookmarks found. Reusing previous interest analysis.")
        analysis = existing_analysis
    else:
        obsidian = read_obsidian()
        print("\nRunning interest analysis...")
        analysis = analyze(bookmarks, obsidian)

    write_markdown(bookmarks, analysis)
    HTML_OUTPUT.write_text(render_html(bookmarks, analysis))

    print(f"\nWritten markdown to {OUTPUT}")
    print(f"Written dashboard to {HTML_OUTPUT}\n")
    print("=" * 60)
    print(analysis)
