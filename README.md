X Bookmark Analyzer

Scrapes your X bookmarks, fetches linked articles, categorizes them with folder taxonomy/Ollama fallback, then gives you both a written analysis and an interactive HTML dashboard.

What Changed From The Original Script

- Uses local Ollama instead of Anthropic Claude
- Uses `gemma4:e2b`
- Uses `uv` for environment setup and running
- Attaches to an already running Google Chrome instance over CDP instead of launching an automated browser for login
- Categorizes bookmarks with Ollama
- Stores derived bookmark timestamps in the cache
- Incrementally adds only new bookmarks on future runs
- Generates an interactive dashboard at `bookmark_dashboard.html`
- Writes output files into your Obsidian vault when configured, otherwise into the directory where you run the script
- Uses a modular package layout under `x_bookmark_analyzer/` for readability

What It Does

- Connects to an existing Chrome instance that you start with remote debugging enabled
- Opens your X bookmarks page in that Chrome session
- Scrolls through and scrapes bookmarks
- Extracts and stores bookmark timestamps from X status IDs
- Fetches and reads linked articles
- Summarizes each bookmark in 1-2 sentences with Ollama
- Assigns a category label to each bookmark with Ollama
- Runs a full analysis: themes, surprises, a clear direction, and tensions
- Builds an HTML dashboard with category drilldowns, clickable tags, heatmap filtering, and usage trends

Project Layout

The CLI entry point is still:

```text
bookmark_analyzer.py
```

The implementation is split into focused modules:

- `x_bookmark_analyzer/config.py`: model settings, output paths, Chrome/CDP settings, and folder taxonomy
- `x_bookmark_analyzer/models.py`: bookmark normalization, timestamp extraction, cache handling, taxonomy matching, and checkpoints
- `x_bookmark_analyzer/scraper.py`: Chrome CDP connection, X bookmark folder scraping, and incremental collection
- `x_bookmark_analyzer/article.py`: URL resolution and lightweight article text extraction
- `x_bookmark_analyzer/enrichment.py`: external URL/article enrichment workflow
- `x_bookmark_analyzer/llm.py`: Ollama calls, summaries, categorization, and interest analysis
- `x_bookmark_analyzer/dashboard.py`: Markdown output, dashboard data shaping, and HTML rendering
- `x_bookmark_analyzer/app.py`: end-to-end orchestration

Requirements

- Python 3.10+
- Google Chrome installed
- Ollama installed and running locally
- The Ollama model `gemma4:e2b` pulled locally
- An X account you can log into in Chrome

Python Dependencies

This repo includes [requirements.txt](/Users/username/x-bookmarks/x_bookmark_analyzer_ollama/requirements.txt):

- `httpx`
- `playwright`

Setup With `uv`

If `uv` is not on your `PATH`, you can use it directly from:

```bash
~/Library/Python/3.13/bin/uv
```

Create the virtual environment:

```bash
~/Library/Python/3.13/bin/uv venv .venv
```

Install dependencies:

```bash
env UV_CACHE_DIR=$PWD/.uv-cache \
  ~/Library/Python/3.13/bin/uv pip install -r requirements.txt --python .venv/bin/python
```

Ollama Setup

Start Ollama and pull the model:

```bash
ollama pull gemma4:e2b
ollama serve
```

The script calls Ollama at:

```text
http://127.0.0.1:11434/api/chat
```

Chrome / X Login Flow

X login was unreliable in Playwright-launched Chrome, so the script now attaches to a Chrome instance that you start yourself.

Start a separate Chrome instance with remote debugging enabled:

```bash
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-playwright-x
```

Why `--user-data-dir` matters:

- It starts a separate Chrome profile for this workflow
- It avoids conflicts with your already running normal Chrome session
- It gives Playwright a clean browser instance to attach to

After that:

1. Open `https://x.com` in that Chrome window
2. Log into X there
3. Keep that Chrome window open
4. Run the script from your project directory

Optional sanity check:

```bash
curl http://127.0.0.1:9222/json/version
```

If Chrome is exposing CDP correctly, that returns JSON.

Run

From the project directory:

```bash
env UV_CACHE_DIR=$PWD/.uv-cache \
  ~/Library/Python/3.13/bin/uv run --python .venv/bin/python bookmark_analyzer.py
```

What Happens On Each Run

- If `bookmarks_cache.json` already exists, the script loads it first
- It then attempts to scrape only bookmarks whose IDs are not already in the cache
- It scrolls the X bookmark folder list until it stops discovering new folders, instead of trusting only the initially rendered folders
- It opens every discovered folder by scrolling back to that folder before collecting posts
- Missing fields are backfilled automatically, including `created_at`
- Existing summaries and categories are reused
- If Chrome/CDP is unavailable but cache already exists, the script can continue from cached data
- If no new bookmarks are found, the previous interest analysis is reused instead of re-running Ollama analysis

If the script cannot connect to Chrome over CDP, it means Chrome was not started with `--remote-debugging-port=9222` or the debugging instance is no longer running.

Folder Coverage

X virtualizes the bookmark folder list, so only the currently visible rows exist in the browser DOM at first. Earlier versions could appear capped around a few dozen folders because they read only that visible slice.

The scraper now:

- Scrolls the folder list until several consecutive scrolls reveal no new folder names
- Tracks folder names across the full virtualized list
- Scrolls back through the list to open each folder before scraping its timeline
- Defaults to scanning every discovered folder on each run for correctness

The tuning knobs live in `x_bookmark_analyzer/config.py`:

```python
FOLDER_SCAN_STABLE_SCROLLS = 8
STOP_ON_FIRST_STALE_FOLDER = False
SCRAPE_TEST_LIMIT = None
```

Keep `STOP_ON_FIRST_STALE_FOLDER = False` when you want maximum confidence that all folders were checked. Set it to `True` only if you are comfortable trading completeness for faster incremental scans.

Categorization Workflow

Categorization now prefers cheap deterministic metadata before using the model:

- If a bookmark's X folder name appears in the configured taxonomy, that folder determines the category
- If folder metadata is unavailable, taxonomy keyword matching is attempted
- Ollama category fallback is disabled by default and only used when explicitly enabled
- Per-bookmark summaries are disabled by default to save compute; the dashboard uses raw text/article content instead

The cache now also stores:

- `created_at`, derived from the X status ID
- `folder_name`, scraped from X bookmark folders when available
- `folder_category`, derived from the configured taxonomy

Example cached bookmark shape:

```json
{
  "id": "2047955648357576920",
  "created_at": "2026-04-25T08:27:30.401000+00:00",
  "author": "Rahul",
  "tweet_url": "https://x.com/i/web/status/2047955648357576920",
  "juice": "A saved overview of how modern LLM behavior is engineered.",
  "category": "LLM Engineering"
}
```

Dashboard

The script writes an interactive dashboard to:

```text
bookmark_dashboard.html
```

The dashboard includes:

- clickable categories in a sidebar
- clickable tag cloud terms that filter matching posts
- bookmark cards grouped by category
- timestamp, author, post link, and article link
- compact excerpts and optional article links
- lazy-loaded cards for better performance
- monthly usage bars
- a year/month heatmap
- yearly bookmark totals
- a Markdown-formatted "What Your Bookmarks Say" analysis that can expand/collapse
- light and dark mode

Output Files

The script currently sets:

```python
OBSIDIAN_VAULT = None
```

Output behavior:

- If that vault exists, files are written there
- If it does not exist, files are written to the directory where you ran the script

Files written:

- `bookmarks_cache.json`
- `bookmark_analysis.md`
- `bookmark_dashboard.html`

Obsidian Notes

If `OBSIDIAN_VAULT` exists, the script also reads Markdown notes from that vault and includes them in the final interest analysis.

In Python, `Path.home()` means your user home directory, for example:

```text
/Users/username
```

The script no longer uses `Path.home()` for output paths by default.

Troubleshooting

- `zsh: command not found: uv`
  Use `~/Library/Python/3.13/bin/uv` directly, or add that directory to your `PATH`.

- `Could not connect to Chrome over CDP`
  Start Chrome first with:

  ```bash
  open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-playwright-x
  ```

- Ollama request failures
  Make sure Ollama is running and that `gemma4:e2b` is installed:

  ```bash
  ollama pull gemma4:e2b
  ollama serve
  ```

- X bookmarks do not load immediately
  The script will prompt you to finish logging into X in the Chrome window and press Enter in the terminal before retrying.
