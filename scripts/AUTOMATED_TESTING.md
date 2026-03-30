# Automated UI testing (Selenium)

Replays scripted user messages against the local chat UI and saves transcripts plus order state JSON.

## Prerequisites

- **Google Chrome** installed (script uses ChromeDriver via Selenium 4).
- **App running** with the chat UI at the URL you pass (default `http://localhost:8000/`).
- Dependencies: `uv sync` (includes `selenium`).

## Run

1. Start the API (from repo root):

   ```bash
   uv run uvicorn src.main:app --reload
   ```

2. In another terminal, run the automation (from repo root):

   ```bash
   uv run python scripts/automated_testing.py
   ```

## Outputs

Writes `convo1.json`, `convo2.json`, … under `automation_outputs/` (override with `--out-dir`).

Each file includes the chat transcript, `order_state` from the `#raw-json` panel if present, and basic UI flags.

## Useful options

| Flag | Default | Purpose |
|------|---------|---------|
| `--base-url` | `http://localhost:8000/` | Chat page URL |
| `--flows-file` | `regression_user_flows.test_menu.json` | Flow definitions (`flows[].user_messages`) |
| `--per-turn-timeout-s` | `60` | Max wait per bot reply |
| `--out-dir` | `automation_outputs` | Where JSON files are saved |

Example:

```bash
uv run python scripts/automated_testing.py --flows-file regression_user_flows.test_menu.json --out-dir automation_outputs
```

## Notes

- The script opens **one Chrome window per flow** and leaves them open; use **Ctrl+C** in the terminal when finished, then close the browsers.
- Ensure Redis/menu are seeded if your chat depends on them (`python scripts/seed_menu.py`).
