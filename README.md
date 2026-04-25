X Bookmark Analyzer

Scrapes your X bookmarks, fetches linked articles, summarizes each one with Ollama, then gives you an honest analysis of what you actually care about and what to pursue next.

What Changed From The Original Script

- Uses local Ollama instead of Anthropic Claude
- Uses `gemma4:e2b`
- Uses `uv` for environment setup and running
- Attaches to an already running Google Chrome instance over CDP instead of launching an automated browser for login
- Writes output files into your Obsidian vault when configured, otherwise into the directory where you run the script

What It Does

- Connects to an existing Chrome instance that you start with remote debugging enabled
- Opens your X bookmarks page in that Chrome session
- Scrolls through and scrapes bookmarks
- Fetches and reads linked articles
- Summarizes each bookmark in 1-2 sentences with Ollama
- Runs a full analysis: themes, surprises, a clear direction, and tensions

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
- `browser-cookie3`

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

Install Playwright's browser dependencies if needed:

```bash
env UV_CACHE_DIR=$PWD/.uv-cache \
  ~/Library/Python/3.13/bin/uv run --python .venv/bin/python playwright install chromium
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

If the script cannot connect to Chrome over CDP, it means Chrome was not started with `--remote-debugging-port=9222` or the debugging instance is no longer running.

Output Files

The script currently sets:

```python
OBSIDIAN_VAULT = Path("/Volumes/Projects/Obsidian Vault")
```

Output behavior:

- If that vault exists, files are written there
- If it does not exist, files are written to the directory where you ran the script

Files written:

- `bookmarks_cache.json`
- `.bookmark_analyzer_cookies.json`
- `bookmark_analysis.md`

Obsidian Notes

If `OBSIDIAN_VAULT` exists, the script also reads Markdown notes from that vault and includes them in the final interest analysis.

In Python, `Path.home()` means your user home directory, for example:

```text
/Users/kirankonathala
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
