# Builder Tracker bot code

Code and writing rules for the Builder Tracker Grok Bot template, made by [@winiam4444](https://x.com/winiam4444).
The imported bot downloads these files from `raw.githubusercontent.com/winiam4444/builder-tracker-projects/main/bot/`
once a day into `/workspace/builder-tracker/code/`. The project list is `../projects.json`, read from the raw URL.

| File | What it does |
|---|---|
| `tracker.py` | CLI the bot calls: config, project picks, own projects, X query plan, cashtag filter, prices, render |
| `prices.py` | Jupiter (Solana) → DexScreener best pool (min $10K liquidity) → CoinGecko fallback; 7d change from own history |
| `format.py` | Number rules ($1.95B, 3.3K+), layout, MCAP sort, quiet-projects line |
| `cashtag.py` | "What people are saying" queries and noise filter |
| `rules.md` | Signal-vs-noise and writing rules the bot follows |
| `config.example.json` | Default settings copied to the user's state on setup |
| `tests/` | `python3 -m unittest discover -s tests` (add `LIVE=1` for live price checks) |

Python 3.9+ standard library only. User data (config, own projects, price history, earlier updates)
stays in `/workspace/builder-tracker/state/` on the user's box (override with `BUILDER_TRACKER_STATE`) and is never uploaded.

Suggest a project for the public list: open an issue or mention @winiam4444 on X.
