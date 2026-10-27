"""Number formatting and layout for Builder Tracker.

Layout per project (sorted by market cap, highest first; projects without a price go last):

    @handle - $TICKER - $MCAP
    $PRICE | 24h +X% | 7d +Y% | Liquidity $Z
    <paragraph>
    <source tweet links>

Modes: "plain" (default) or "emoji" (each paragraph starts with a green circle marker).
"""
from __future__ import annotations

import math
import re
from datetime import datetime

GREEN = "\U0001F7E2"
_UNITS = [(1e9, "B"), (1e6, "M"), (1e3, "K")]


def _trunc1(x: float) -> float:
    return math.floor(x * 10 + 1e-9) / 10


def compact(n: float, money: bool = False, plus: bool = True) -> str:
    """K/M/B with one decimal at most.

    plus=True (claims in paragraphs): extra precision is cut and marked with '+': 3,345 -> 3.3K+.
    plus=False (data lines: MCAP, liquidity): rounded, no '+'; K has no decimal (810K), M and B one (1.8M).
    """
    neg = n < 0
    n = abs(n)
    unit, div = "", 1.0
    for d, u in _UNITS:
        if n >= d:
            div, unit = d, u
            break
    v = n / div
    if plus:
        shown = _trunc1(v)
        exact = abs(shown * div - n) < 1e-6 * max(1.0, n)
    else:
        shown = round(v) if unit == "K" else round(v, 1)  # data lines: $810K, $1.8M, $2.4B
        if shown >= 1000 and unit != "B":  # 999.96K -> 1M
            nxt = {"": "K", "K": "M", "M": "B"}[unit]
            shown, unit = round(n / {"K": 1e3, "M": 1e6, "B": 1e9}[nxt], 1), nxt
        elif unit == "K" and shown >= 1000:
            shown, unit = round(n / 1e6, 1), "M"
        exact = True
    s = f"{shown:.1f}".rstrip("0").rstrip(".")
    return f"{'-' if neg else ''}{'$' if money else ''}{s}{unit}{'' if exact else '+'}"


def price(p: float | None) -> str:
    """Token price: K/M/B from $1,000, two decimals from $1, else four significant digits."""
    if p is None:
        return "n/a"
    if p >= 1000:
        return compact(p, money=True, plus=False)
    if p >= 1:
        return f"${p:.2f}"
    if p == 0:
        return "$0"
    digits = 4 - int(math.floor(math.log10(p))) - 1
    return f"${p:.{digits}f}".rstrip("0")


def pct(x: float | None) -> str | None:
    if x is None:
        return None
    return f"{'+' if x >= 0 else ''}{x:.1f}%"


# ---------- enforce the number rule on written paragraphs ----------

_PROTECT = re.compile(r"https?://\S+|@\w+|\b0x[0-9a-fA-F]{6,}\b|\b[1-9A-HJ-NP-Za-km-z]{32,44}\b|\bv?\d+\.\d+\.\d+\b"
                      r"|\b\d{1,2}:\d{2}\b|\b(?:19|20)\d{2}\b")
_NUM = re.compile(r"(?<![\w.,])(\$?)(\d{1,3}(?:,\d{3})+|\d{4,})(\.\d+)?(?!\w|,\d|\.\d)(\+?)(%?)")
_DEC = re.compile(r"(?<![\w.,])(\$?)(\d{1,3})\.(\d{2,})(?!\w|[.,]\d)(%?)")


def enforce_numbers(text: str) -> str:
    """Rewrite long-form figures to K/M/B with one decimal and a '+' for dropped precision.

    '$464,628' -> '$464.6K+', '7,115,447,857 UBI' -> '7.1B+ UBI', '522.69 USDC' -> '522.6+ USDC',
    '$1,000,000' -> '$1M'. Leaves URLs, @handles, contract addresses, versions, clock times and years alone.
    Percentages are rounded to one decimal: '7.12%' -> '7.1%'.
    """
    slots: list[str] = []

    def hide(m):
        slots.append(m.group(0))
        return f"\x00{len(slots) - 1}\x00"

    t = _PROTECT.sub(hide, text)

    def big(m):
        dollar, whole, frac, had_plus, pc = m.groups()
        if pc:
            return m.group(0)
        n = float(whole.replace(",", "") + (frac or ""))
        out = compact(n, money=bool(dollar))
        if had_plus and not out.endswith("+"):
            out += "+"
        return out

    t = _NUM.sub(big, t)

    def dec(m):
        dollar, whole, frac, pc = m.groups()
        n = float(f"{whole}.{frac}")
        if pc:
            return f"{round(n, 1):.1f}".rstrip("0").rstrip(".") + "%"
        shown = _trunc1(n)
        s = f"{shown:.1f}".rstrip("0").rstrip(".")
        return f"{dollar}{s}{'' if abs(shown - n) < 1e-9 else '+'}"

    t = _DEC.sub(dec, t)
    return re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], t)


# ---------- layout ----------

def mcap(n: float) -> str:
    """Header MCAP: B keeps two decimals ($1.95B), K and M as data lines ($810K, $2.6M)."""
    if n >= 999_995_000:
        return "$" + f"{round(n / 1e9, 2):.2f}".rstrip("0").rstrip(".") + "B"
    return compact(n, money=True, plus=False)


def header_line(project: dict, pr: dict | None) -> str:
    parts = [f"@{project['x_project']}", f"${project['ticker']}" if project.get("ticker")
             else f"{project['chain']}:{project['contract_address']}"]
    if pr and pr.get("mcap_usd"):
        parts.append(mcap(pr["mcap_usd"]))
    return " - ".join(parts)


def price_line(pr: dict | None) -> str | None:
    if not pr or pr.get("price_usd") is None:
        return None
    bits = [price(pr["price_usd"])]
    if pct(pr.get("change_24h")):
        bits.append(f"24h {pct(pr['change_24h'])}")
    if pct(pr.get("change_7d")):
        bits.append(f"7d {pct(pr['change_7d'])}")
    if pr.get("liquidity_usd"):
        bits.append(f"Liquidity {compact(pr['liquidity_usd'], money=True, plus=False)}")
    return " | ".join(bits)


def tweet_url(handle: str, tweet_id: str) -> str:
    return f"https://x.com/{handle}/status/{tweet_id}"


COMMUNITY_LABEL = "What people are saying"


def _sources(para: dict) -> list[str]:
    return [s if isinstance(s, str) else tweet_url(s["handle"], s["id"]) for s in para.get("sources", [])]


def project_block(project: dict, pr: dict | None, paragraphs: list[dict], mode: str = "plain",
                  community: dict | None = None) -> str:
    """paragraphs: [{"text": str, "sources": [{"handle":..., "id":...} | url str, ...]}]
    community: one cashtag summary {"text", "sources"} or None (skipped when nothing stood out).
    It always sits under the project's own paragraphs, after the label line, without the emoji marker."""
    lines = [header_line(project, pr)]
    pl = price_line(pr)
    if pl:
        lines.append(pl)
    for para in paragraphs:
        text = enforce_numbers(para["text"].strip())
        lines.append("")
        lines.append(f"{GREEN} {text}" if mode == "emoji" else text)
        lines.extend(_sources(para))
    if community and community.get("text", "").strip():
        lines += ["", COMMUNITY_LABEL, enforce_numbers(community["text"].strip())]
        lines.extend(_sources(community))
    return "\n".join(lines)


def sort_key(item):
    pr = item[1] or {}
    return -(pr.get("mcap_usd") or -1)


def daily_update(items: list[tuple], when: datetime,
                 mode: str = "plain", quiet: list[dict] | None = None, window: str = "last ~24 hours",
                 title: str = "Builder updates", footer: str | None = None) -> str:
    """items: (project, price dict, paragraphs[, community]). A project with neither paragraphs nor a
    community summary is moved to the one-line quiet list at the bottom."""
    blocks = [f"{title}, {when.day} {when.strftime('%b %Y')} ({window})"]
    quiet = list(quiet or [])
    for item in sorted(items, key=sort_key):
        project, pr, paras = item[:3]
        community = item[3] if len(item) > 3 else None
        if not paras and not (community and community.get("text")):
            quiet.append(project)
            continue
        blocks.append(project_block(project, pr, paras, mode, community))
    if quiet:
        blocks.append("No news in the window: " + ", ".join(f"@{p['x_project']}" for p in quiet))
    if footer:
        blocks.append(footer)
    return "\n\n".join(blocks) + "\n"


def weekly_footer() -> str:
    return "Winiam's Builder Tracker, made by @winiam4444"
