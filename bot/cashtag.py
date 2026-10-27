"""Cashtag scan: what the community said about a project's $TICKER in the window.

The agent makes the X calls (built-in search_posts_all); this module builds the queries and
cleans the results so the agent only summarizes posts that matter.

Facts learned from live runs:
- The built-in search strips "$" from queries, so the cashtag operator cannot be used. The query
  searches the bare ticker word plus project context, and filter_posts() then keeps posts that
  really carry the project (cashtag in the text, handle, name, contract address or product terms).
- min_likes: was not honored (posts with 0 likes came back), so engagement is ranked locally.
- sort_order "relevancy" surfaces engaged posts better than "recency" on big tickers.
"""
from __future__ import annotations

import re

CHAIN_WORDS = {
    "solana": ["solana"],
    "robinhood": ["robinhood chain", "robinhood"],
    "arc": ["@arc", "on arc", "arc chain", "arc network", "arc ecosystem"],
}

NOISE = re.compile(
    r"giveaway|airdrop (?:is )?live|claim (?:now|your)|free \$?\d+|bonus for users|\bdm me\b|"
    r"\bcto signal\b|\bpump signal\b|\b\d{2,}x\b|ape (?:in|now)|send it|wagmi|lfg|"
    r"report id:|join (?:our|my) (?:tg|telegram)|t\.me/|dexscreener\.com|gmgn\.ai|"
    r"\bca:\s|presale|whitelist spots",
    re.I,
)
PRICE_ONLY = re.compile(r"^(?:[\W\d\s$%kmb.x+-]|pump|dump|moon|chart|ath|mc|mcap|buy|sell|bullish|bearish)+$", re.I)
TRACKER_LAYOUT = re.compile(r"^@\w+ - \$\w+ - \$[\d.]+[KMB]?", re.M)  # our own update format, reposted
CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9_]{0,14})\b")

# tickers that are also common words or shared with other coins: require project context
COLLIDES = {"RAM", "PUMP", "KAIRO", "ARC", "UP", "SOL", "AI", "X", "ONE", "MOON", "CAT", "DOG", "GAME"}


def context_terms(project: dict) -> list[str]:
    terms = [project.get("name", ""), project.get("x_project", "")]
    terms += [project.get("contract_address", "")]
    terms += CHAIN_WORDS.get(project.get("chain", ""), [])
    terms += project.get("products", [])  # optional, e.g. ["Buy & Earn", "KLIK"]
    return [t for t in terms if t]


def own_handles(project: dict, extra: list[str] | None = None) -> set[str]:
    hs = [project.get("x_project", "")] + project.get("x_founders", []) + project.get("x_team", [])
    return {h.lower().lstrip("@") for h in hs + (extra or []) if h}


def build_queries(project: dict, exclude: list[str] | None = None, lang: str | None = "en") -> list[str]:
    """Return 1 or 2 queries. Call the second only when the first keeps fewer than MIN_KEEP posts."""
    t = project["ticker"]
    outs = " ".join(f"-from:{h}" for h in sorted(own_handles(project, exclude)))
    ctx = []
    for term in context_terms(project):
        if term.startswith("0x") or len(term) > 30:
            ctx.append(term)
        elif term == project.get("x_project"):
            ctx.append("@" + term)
        elif " " in term or "&" in term:
            ctx.append(f'"{term}"')
        else:
            ctx.append(term)
    ctx_part = "(" + " OR ".join(dict.fromkeys(ctx)) + ")"
    lang_part = f" lang:{lang}" if lang else ""
    q1 = f"{t} {ctx_part} -is:retweet -is:reply{lang_part} {outs}".strip()
    q2 = f"{t} -is:retweet {outs}".strip() if t.upper() not in COLLIDES else f"{t} {ctx_part} -is:retweet {outs}".strip()
    return [q1, q2]


MIN_KEEP = 5


CRYPTO_WORDS = re.compile(r"\b(dex|lp|swap|token|onchain|on-chain|defi|liquidity|fees?|tvl|volume|"
                          r"pool|chain|wallet|launchpad|memecoin|meme coin|airdrop|staking|holders?|usdc)\b", re.I)


def _has_context(text: str, project: dict) -> bool:
    """Strong: the project handle or contract address. Otherwise the cashtag or the project name has to
    come with chain, product or crypto words. A bare name ("Ramses II", "Kairo") is not enough."""
    low = text.lower()
    t = project["ticker"].upper()
    handle = project.get("x_project", "").lower()
    ca = project.get("contract_address", "").lower()
    if (handle and "@" + handle in low) or (ca and ca in low):
        return True
    tagged = t in {m.upper() for m in CASHTAG.findall(text)}
    named = project.get("name", "").lower() in low
    chainish = any(w in low for w in CHAIN_WORDS.get(project.get("chain", ""), []))
    product = any(p.lower() in low for p in project.get("products", []))
    crypto = bool(CRYPTO_WORDS.search(text))
    if tagged and t not in COLLIDES:
        return True
    return (tagged or named) and (chainish or product or crypto)


def score(post: dict) -> int:
    m = post.get("public_metrics", {})
    return m.get("like_count", 0) + 2 * m.get("retweet_count", 0) + m.get("reply_count", 0) + 2 * m.get("quote_count", 0)


def filter_posts(resp: dict, project: dict, exclude: list[str] | None = None,
                 min_followers: int = 50, keep: int = 12) -> list[dict]:
    """resp: raw search_posts_all response. Returns cleaned posts, best first, with 'username' set."""
    users = {u["id"]: u for u in resp.get("includes", {}).get("users", [])}
    skip = own_handles(project, exclude)
    seen_text, out = set(), []
    for p in resp.get("data", []):
        u = users.get(p.get("author_id"), {})
        name = (u.get("username") or "").lower()
        text = p.get("text", "")
        norm = re.sub(r"https?://\S+|\s+", " ", text).strip().lower()
        if not name or name in skip:
            continue
        if any(r.get("type") == "retweeted" for r in p.get("referenced_tweets", []) or []):
            continue
        if NOISE.search(text) or TRACKER_LAYOUT.search(text) or PRICE_ONLY.match(norm):
            continue
        if len(CASHTAG.findall(text)) >= 6 and not re.search(r"\$\d", text):  # bare ticker lists, shill rows
            continue
        if u.get("public_metrics", {}).get("followers_count", 0) < min_followers and score(p) == 0:
            continue
        if norm[:120] in seen_text:  # copy-paste bots
            continue
        if not _has_context(text, project):
            continue
        seen_text.add(norm[:120])
        out.append(dict(p, username=u.get("username")))
    out.sort(key=score, reverse=True)
    return out[:keep]
