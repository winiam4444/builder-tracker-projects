import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import format as fmt  # noqa: E402
import prices  # noqa: E402
import cashtag  # noqa: E402

PROJECTS_URL = "https://raw.githubusercontent.com/winiam4444/builder-tracker-projects/main/projects.json"
CA = "0x5173D45A1191eE33cBB7D8c7e65f21B04eD54802"


def pair(addr, liq, price="1.0", base=True, name="p"):
    other = "0xOTHER"
    return {"pairAddress": name, "dexId": "x", "priceUsd": price, "liquidity": {"usd": liq},
            "marketCap": 1e6, "priceChange": {"h24": 1.0},
            "baseToken": {"address": addr if base else other}, "quoteToken": {"address": other if base else addr}}


class PoolRules(unittest.TestCase):
    def test_most_liquidity_wins(self):
        pools = [pair(CA, 50_000, name="a"), pair(CA, 400_000, name="b"), pair(CA, 12_000, name="c")]
        self.assertEqual(prices.best_pool(pools, CA)["pairAddress"], "b")

    def test_tiny_pools_ignored(self):
        self.assertIsNone(prices.best_pool([pair(CA, 4), pair(CA, 9_999)], CA))

    def test_quote_side_pool_ignored(self):
        pools = [pair(CA, 900_000, base=False, name="q"), pair(CA, 20_000, name="b")]
        self.assertEqual(prices.best_pool(pools, CA)["pairAddress"], "b")

    def test_case_insensitive_address(self):
        self.assertIsNotNone(prices.best_pool([pair(CA.lower(), 20_000)], CA))

    def test_jupiter_min_liquidity(self):
        p = prices.Price("x", "solana", "m")
        self.assertFalse(prices.from_jupiter(p, {"usdPrice": 1, "liquidity": 500}))
        self.assertTrue(prices.from_jupiter(p, {"usdPrice": 1, "liquidity": 50_000, "mcap": 2e6,
                                                "stats24h": {"priceChange": -3}}))
        self.assertEqual(p.change_24h, -3)

    def test_7d_from_history(self):
        now = datetime(2026, 10, 27, 19, 0, tzinfo=timezone.utc)
        r = prices.Price("x", "arc", CA, price_usd=1.1)
        hist = {prices._key(r): [{"ts": (now - timedelta(days=7, hours=2)).isoformat(), "price": 1.0}]}
        self.assertAlmostEqual(prices.change_7d(hist, r, now), 10.0, places=6)
        self.assertIsNone(prices.change_7d({}, r, now))


class Numbers(unittest.TestCase):
    def test_compact(self):
        c = fmt.compact
        self.assertEqual(c(3345), "3.3K+")
        self.assertEqual(c(1_000_000, money=True), "$1M")
        self.assertEqual(c(600_000, money=True), "$600K")
        self.assertEqual(c(1_834_000, money=True, plus=False), "$1.8M")
        self.assertEqual(c(999_960, money=True, plus=False), "$1M")
        self.assertEqual(c(1.97e9, money=True, plus=False), "$2B")
        self.assertEqual(c(850_259, money=True, plus=False), "$850K")
        self.assertEqual(c(999_700, money=True, plus=False), "$1M")

    def test_enforce(self):
        e = fmt.enforce_numbers
        self.assertEqual(e("on $464,628 of volume"), "on $464.6K+ of volume")
        self.assertEqual(e("7,115,447,857 UBI"), "7.1B+ UBI")
        self.assertEqual(e("522.69 USDC"), "522.6+ USDC")
        self.assertEqual(e("$1,000,000 raised"), "$1M raised")
        self.assertEqual(e("$1,500,000, $750,000 and $250,000."), "$1.5M, $750K and $250K.")
        self.assertEqual(e("paid 522.69, then"), "paid 522.6+, then")
        self.assertEqual(e("7.12% of supply"), "7.1% of supply")
        keep = "v1.4.0 at 20:00 CET in 2026 https://x.com/a/status/2115070244234441087 " + CA + " @user12345"
        self.assertEqual(e(keep), keep)
        self.assertEqual(e("$2.5M and 15 networks"), "$2.5M and 15 networks")

    def test_price(self):
        self.assertEqual(fmt.price(0.004285), "$0.004285")
        self.assertEqual(fmt.price(12.345), "$12.35")
        self.assertEqual(fmt.price(None), "n/a")


class Layout(unittest.TestCase):
    proj = {"x_project": "RamsesExchange", "ticker": "RAM", "chain": "robinhood", "contract_address": CA}
    pr = {"price_usd": 0.03162, "mcap_usd": 2_636_576, "change_24h": -0.32, "change_7d": None, "liquidity_usd": 385_811}
    paras = [{"text": "Ramses crossed $31,000,000,000 in volume.", "sources": [{"handle": "RamsesExchange", "id": "1"}]}]

    def test_plain(self):
        out = fmt.project_block(self.proj, self.pr, self.paras, "plain")
        self.assertEqual(out.splitlines(), [
            "@RamsesExchange - $RAM - $2.6M",
            "$0.03162 | 24h -0.3% | Liquidity $386K",
            "",
            "Ramses crossed $31B in volume.",
            "https://x.com/RamsesExchange/status/1"])
        self.assertNotIn(fmt.GREEN, out)

    def test_emoji(self):
        out = fmt.project_block(self.proj, self.pr, self.paras, "emoji")
        self.assertIn(fmt.GREEN + " Ramses crossed $31B in volume.", out)

    def test_no_price(self):
        out = fmt.project_block(self.proj, None, self.paras)
        self.assertTrue(out.startswith("@RamsesExchange - $RAM\n\n"))

    def test_sorted_by_mcap(self):
        a = dict(self.proj, x_project="A")
        b = dict(self.proj, x_project="B")
        out = fmt.daily_update([(a, {"price_usd": 1, "mcap_usd": 1e5}, self.paras),
                                (b, {"price_usd": 1, "mcap_usd": 1e8}, self.paras),
                                (dict(self.proj, x_project="C"), None, self.paras)],
                               datetime(2026, 10, 27))
        self.assertLess(out.index("@B"), out.index("@A"))
        self.assertLess(out.index("@A"), out.index("@C"))


class Headers(unittest.TestCase):
    def test_mcap_two_decimals_for_b(self):
        self.assertEqual(fmt.mcap(1.95e9), "$1.95B")
        self.assertEqual(fmt.mcap(1_973_671_531), "$1.97B")
        self.assertEqual(fmt.mcap(2.0e9), "$2B")
        self.assertEqual(fmt.mcap(850_259), "$850K")
        self.assertEqual(fmt.mcap(2_633_168), "$2.6M")
        self.assertEqual(fmt.header_line({"x_project": "Pumpfun", "ticker": "PUMP"}, {"mcap_usd": 1.95e9}),
                         "@Pumpfun - $PUMP - $1.95B")


class Community(unittest.TestCase):
    proj = {"name": "Ramses", "x_project": "RamsesExchange", "ticker": "RAM", "chain": "robinhood",
            "contract_address": CA, "x_founders": [], "x_team": ["D333z"]}
    paras = [{"text": "Zaps are live on Ramses.", "sources": [{"handle": "RamsesExchange", "id": "1"}]}]
    comm = {"text": "@someone said Ramses processed 1,234,567 in volume.", "sources": [{"handle": "someone", "id": "9"}]}

    def test_block_under_official(self):
        out = fmt.project_block(self.proj, None, self.paras, "emoji", self.comm).splitlines()
        i = out.index(fmt.COMMUNITY_LABEL)
        self.assertGreater(i, out.index(fmt.GREEN + " Zaps are live on Ramses."))
        self.assertEqual(out[i + 1], "@someone said Ramses processed 1.2M+ in volume.")
        self.assertEqual(out[i + 2], "https://x.com/someone/status/9")

    def test_skipped_when_empty(self):
        out = fmt.project_block(self.proj, None, self.paras, "plain", {"text": "", "sources": []})
        self.assertNotIn(fmt.COMMUNITY_LABEL, out)

    def test_quiet_line(self):
        out = fmt.daily_update([(self.proj, None, [], None), (dict(self.proj, x_project="B"), None, [], self.comm)],
                               datetime(2026, 10, 27))
        self.assertTrue(out.rstrip().endswith("No news in the window: @RamsesExchange"))
        self.assertIn("@B - $RAM", out)

    def _resp(self, rows):
        users, data = [], []
        for i, (name, text, likes, followers) in enumerate(rows):
            users.append({"id": str(i), "username": name, "public_metrics": {"followers_count": followers}})
            data.append({"id": str(100 + i), "author_id": str(i), "text": text,
                         "public_metrics": {"like_count": likes, "retweet_count": 0, "reply_count": 0, "quote_count": 0}})
        return {"data": data, "includes": {"users": users}}

    def test_filter(self):
        resp = self._resp([
            ("D333z", "$RAM fees on Ramses are up", 50, 9000),                  # team: covered already
            ("RamsesExchange", "Ramses LP manager", 50, 9000),                  # project itself
            ("history", "Ramses II was a pharaoh", 40, 9000),                   # name collision
            ("pc", "need more RAM for my pc", 30, 9000),                        # ticker collision
            ("shill", "$RAM giveaway! claim now 100x", 30, 9000),               # noise
            ("bot", "$RAM $UP $PONS $SLVR $ANT $RAID", 5, 9000),               # ticker list
            ("tracker", "@RamsesExchange - $RAM - $2.6M\nnews", 3, 9000),        # our own layout
            ("fan", "the Ramses LP manager is smooth on robinhood chain", 2, 900),
            ("analyst", "$RAM earned $25K in fees, best DEX on Robinhood", 9, 3000),
            ("ca", "watching " + CA.lower(), 1, 300),
        ])
        kept = [p["username"] for p in cashtag.filter_posts(resp, self.proj, exclude=["sometracker"])]
        self.assertEqual(kept, ["analyst", "fan", "ca"])

    def test_queries(self):
        qs = cashtag.build_queries(self.proj, ["sometracker"])
        self.assertEqual(len(qs), 2)
        self.assertNotIn("$", qs[0])  # the built-in search strips $, so the ticker goes in bare
        for part in ("RAM (", "@RamsesExchange", CA, "-is:retweet", "lang:en", "-from:d333z", "-from:sometracker"):
            self.assertIn(part, qs[0])
        self.assertIn("(", qs[1])  # colliding ticker keeps its context on the second call too


@unittest.skipUnless(os.environ.get("LIVE") == "1", "set LIVE=1 to call the real APIs")
class Live(unittest.TestCase):
    def test_three_chains(self):
        allp = prices.http_json(PROJECTS_URL)
        projects = [p for p in allp
                    if p["id"] in ("pump", "ramses", "kairo", "meteora")]
        res = {r.project_id: r for r in prices.get_prices(projects)}
        for pid in ("pump", "ramses", "kairo", "meteora"):
            self.assertTrue(res[pid].ok, res[pid])
            self.assertGreaterEqual(res[pid].liquidity_usd, prices.MIN_LIQUIDITY_USD)
        self.assertEqual(res["pump"].source, "jupiter")
        self.assertEqual(res["ramses"].source, "dexscreener")
        self.assertEqual(res["kairo"].source, "dexscreener")


if __name__ == "__main__":
    unittest.main(verbosity=2)
