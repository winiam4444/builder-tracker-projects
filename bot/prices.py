"""Price fetcher for Builder Tracker. Python stdlib only.

Rules:
- Solana tokens: Jupiter tokens v2 first (keyless, ~30 calls/min, up to 100 mints per call).
  It returns price, market cap, 24h change and liquidity in one call.
- Every chain (and Solana fallback): DexScreener, taking the pool with the MOST liquidity
  where the token is the base token. A pool needs at least MIN_LIQUIDITY_USD (default $10K).
  If no pool qualifies, the project gets no price line (never a price from a $4 pool).
- CoinGecko keyless is the last fallback, only for projects with a coingecko_id.
- 7d change comes from the bot's own stored history (price_history.json), not from an API.

Usage (normally through tracker.py prices):
    python3 prices.py --projects projects.json --ids pump,ramses,kairo [--history state/price_history.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

MIN_LIQUIDITY_USD = 10_000
DEX_TOKEN_PAIRS = "https://api.dexscreener.com/token-pairs/v1/{chain}/{address}"  # all pools for one token, 300/min
JUP_TOKENS_V2 = "https://lite-api.jup.ag/tokens/v2/search?query={mints}"           # up to 100 mints, comma-separated
JUP_PRICE_V3 = "https://lite-api.jup.ag/price/v3?ids={mints}"                      # price-only fallback
COINGECKO_MARKETS = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
                     "&ids={ids}&price_change_percentage=24h")
TIMEOUT = 20
HEADERS = {"User-Agent": "builder-tracker/1.0", "Accept": "application/json"}


@dataclass
class Price:
    project_id: str
    chain: str
    address: str
    price_usd: float | None = None
    mcap_usd: float | None = None
    change_24h: float | None = None
    change_7d: float | None = None
    liquidity_usd: float | None = None
    source: str | None = None          # jupiter | dexscreener | coingecko
    pool: str | None = None            # pool address when from DexScreener
    dex: str | None = None
    note: str | None = None            # why there is no price, if any

    @property
    def ok(self) -> bool:
        return self.price_usd is not None


class RateLimiter:
    """Simple per-host spacing so a 25-project run never bursts past a limit."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / per_minute
        self.last = 0.0

    def wait(self):
        delay = self.last + self.interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()


LIMITS = {"dexscreener": RateLimiter(240), "jupiter": RateLimiter(25), "coingecko": RateLimiter(8)}


def http_json(url: str, timeout: float = TIMEOUT, retries: int = 3):
    """GET a JSON URL with the stdlib. Retries 429 and 5xx with a short backoff."""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _get(url: str, host: str, session=None):
    """`session` is kept for tests: any object with .get_json(url) replaces the network."""
    LIMITS[host].wait()
    if session is not None and hasattr(session, "get_json"):
        return session.get_json(url)
    return http_json(url)


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# ---------- pool selection (pure, unit-tested) ----------

def best_pool(pairs: list[dict], address: str, min_liq: float = MIN_LIQUIDITY_USD) -> dict | None:
    """Pick the DexScreener pool with the most USD liquidity where `address` is the BASE token.

    Pools where the token is only the quote token are skipped (their priceUsd is the other token's).
    Pools without a USD liquidity figure or below `min_liq` are skipped.
    """
    addr = address.lower()
    eligible = []
    for p in pairs or []:
        base = ((p.get("baseToken") or {}).get("address") or "").lower()
        liq = _f((p.get("liquidity") or {}).get("usd"))
        if base != addr or liq is None or liq < min_liq or _f(p.get("priceUsd")) is None:
            continue
        eligible.append((liq, p))
    if not eligible:
        return None
    return max(eligible, key=lambda t: t[0])[1]


def from_dex_pool(price: Price, pool: dict) -> Price:
    price.price_usd = _f(pool.get("priceUsd"))
    price.mcap_usd = _f(pool.get("marketCap")) or _f(pool.get("fdv"))
    price.change_24h = _f((pool.get("priceChange") or {}).get("h24"))
    price.liquidity_usd = _f((pool.get("liquidity") or {}).get("usd"))
    price.source, price.pool, price.dex = "dexscreener", pool.get("pairAddress"), pool.get("dexId")
    return price


def from_jupiter(price: Price, tok: dict, min_liq: float = MIN_LIQUIDITY_USD) -> bool:
    liq = _f(tok.get("liquidity"))
    if _f(tok.get("usdPrice")) is None or liq is None or liq < min_liq:
        return False
    price.price_usd = _f(tok.get("usdPrice"))
    price.mcap_usd = _f(tok.get("mcap")) or _f(tok.get("fdv"))
    price.change_24h = _f((tok.get("stats24h") or {}).get("priceChange"))
    price.liquidity_usd = liq
    price.source = "jupiter"
    return True


# ---------- fetchers ----------

def fetch_jupiter(mints: list[str], session=None) -> dict[str, dict]:
    out = {}
    for i in range(0, len(mints), 100):
        chunk = mints[i:i + 100]
        data = _get(JUP_TOKENS_V2.format(mints=",".join(chunk)), "jupiter", session) or []
        for tok in data:
            if tok.get("id") in chunk:
                out[tok["id"]] = tok
    return out


def fetch_dex_pairs(chain: str, address: str, session=None) -> list[dict]:
    return _get(DEX_TOKEN_PAIRS.format(chain=chain, address=address), "dexscreener", session) or []


def fetch_coingecko(ids: list[str], session=None) -> dict[str, dict]:
    if not ids:
        return {}
    data = _get(COINGECKO_MARKETS.format(ids=",".join(ids)), "coingecko", session) or []
    return {c["id"]: c for c in data}


def get_prices(projects: list[dict], min_liq: float = MIN_LIQUIDITY_USD,
               history_path: str | None = None, session=None) -> list[Price]:
    results = {p["id"]: Price(p["id"], p["chain"], p["contract_address"]) for p in projects}

    # 1) Jupiter for Solana, one batched call
    sol = [p for p in projects if p["chain"] == "solana"]
    if sol:
        try:
            jup = fetch_jupiter([p["contract_address"] for p in sol], session)
        except Exception as e:  # noqa: BLE001
            jup = {}
            for p in sol:
                results[p["id"]].note = f"jupiter error: {e}"
        for p in sol:
            tok = jup.get(p["contract_address"])
            if tok:
                from_jupiter(results[p["id"]], tok, min_liq)

    # 2) DexScreener best pool for everything still without a price
    for p in projects:
        r = results[p["id"]]
        if r.ok:
            continue
        try:
            pool = best_pool(fetch_dex_pairs(p["chain"], p["contract_address"], session),
                             p["contract_address"], min_liq)
        except Exception as e:  # noqa: BLE001
            r.note = f"dexscreener error: {e}"
            continue
        if pool:
            from_dex_pool(r, pool)
        else:
            r.note = f"no pool with ${int(min_liq):,}+ liquidity"

    # 3) CoinGecko fallback (keyless) only where a coingecko_id exists
    missing = [p for p in projects if not results[p["id"]].ok and p.get("coingecko_id")]
    if missing:
        try:
            cg = fetch_coingecko([p["coingecko_id"] for p in missing], session)
            for p in missing:
                c = cg.get(p["coingecko_id"])
                if c and c.get("current_price") is not None:
                    r = results[p["id"]]
                    r.price_usd, r.mcap_usd = _f(c["current_price"]), _f(c.get("market_cap"))
                    r.change_24h = _f(c.get("price_change_percentage_24h"))
                    r.source, r.note = "coingecko", None
        except Exception as e:  # noqa: BLE001
            for p in missing:
                results[p["id"]].note = (results[p["id"]].note or "") + f"; coingecko error: {e}"

    out = list(results.values())
    if history_path:
        hist = load_history(history_path)
        now = datetime.now(timezone.utc)
        for r in out:
            if r.ok:
                r.change_7d = change_7d(hist, r, now)
                record(hist, r, now)
        save_history(history_path, hist)
    return out


# ---------- own price history for 7d change ----------

def _key(r: Price) -> str:
    return f"{r.chain}:{r.address.lower() if r.address.startswith('0x') else r.address}"


def load_history(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}


def save_history(path: str, hist: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(hist, fh, indent=1)


def record(hist: dict, r: Price, now: datetime, keep_days: int = 35):
    rows = hist.setdefault(_key(r), [])
    rows.append({"ts": now.isoformat(timespec="seconds"), "price": r.price_usd})
    cutoff = now - timedelta(days=keep_days)
    hist[_key(r)] = [x for x in rows if datetime.fromisoformat(x["ts"]) >= cutoff]


def change_7d(hist: dict, r: Price, now: datetime, tolerance_h: float = 18) -> float | None:
    """% change against the stored price closest to 7 days ago (within +/- tolerance)."""
    target = now - timedelta(days=7)
    best = None
    for x in hist.get(_key(r), []):
        dt = abs((datetime.fromisoformat(x["ts"]) - target).total_seconds()) / 3600
        if dt <= tolerance_h and (best is None or dt < best[0]):
            best = (dt, x["price"])
    if not best or not best[1]:
        return None
    return (r.price_usd / best[1] - 1) * 100


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", required=True)
    ap.add_argument("--ids", help="comma-separated project ids (default: all)")
    ap.add_argument("--history")
    ap.add_argument("--min-liquidity", type=float, default=MIN_LIQUIDITY_USD)
    a = ap.parse_args(argv)
    with open(a.projects) as fh:
        projects = json.load(fh)
    if a.ids:
        want = a.ids.split(",")
        projects = [p for p in projects if p["id"] in want]
    res = get_prices(projects, a.min_liquidity, a.history)
    json.dump([asdict(r) for r in res], sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
