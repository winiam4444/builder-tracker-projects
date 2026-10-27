# Winiam's Builder Tracker

Curated list of crypto projects that are actually building, maintained by [@winiam4444](https://x.com/winiam4444). The list covers Robinhood Chain, Solana, and Arc. It does not include memecoins.

Bots fetch the raw file from the default branch every day:

https://raw.githubusercontent.com/winiam4444/builder-tracker-projects/main/projects.json

The curator updates this list. To follow a project of your own, add it inside your bot.

## Counts

| Chain | Projects |
| --- | ---: |
| Robinhood Chain (`robinhood`) | 284 |
| Solana (`solana`) | 159 |
| Arc (`arc`) | 28 |
| **Total** | **471** |

## Fields

`projects.json` is a JSON array. One object per project:

| Field | Description |
| --- | --- |
| `name` | Project name |
| `id` | Stable id. Never changes. |
| `ticker` | Token ticker |
| `chain` | Chain id. Matches DexScreener: `robinhood`, `solana`, `arc` |
| `contract_address` | Contract address |
| `x_project` | X handle of the project |
| `x_founders` | X handles of the founders |
| `x_team` | X handles of the team |
| `x_notable` | X handles of notable accounts |
| `competitors` | Ids of competing projects |
| `category` | List of categories |
| `coingecko_id` | Optional CoinGecko id |
| `status` | `active` or `paused` |
| `added` | Date the project was added (`YYYY-MM-DD`) |
