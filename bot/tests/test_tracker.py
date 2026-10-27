"""Offline tests for tracker.py: state in a temp dir, project list from tests/fixtures."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import tracker  # noqa: E402

OWN = {"name": "My Token", "ticker": "MYT", "chain": "solana",
       "contract_address": "So11111111111111111111111111111111111111112", "x_project": "@mytoken"}


class TrackerState(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["BUILDER_TRACKER_STATE"] = self.dir
        os.makedirs(os.path.join(self.dir, "cache"))
        shutil.copy(os.path.join(HERE, "fixtures", "projects.json"), os.path.join(self.dir, "cache", "projects.json"))
        self.cfg = tracker.default_config()
        tracker.save_config(self.cfg)

    def tearDown(self):
        shutil.rmtree(self.dir)
        os.environ.pop("BUILDER_TRACKER_STATE", None)

    def test_cache_used_without_network(self):
        ids = {p["id"] for p in tracker.curated(url="http://127.0.0.1:9/none.json")}
        self.assertEqual(ids, {"pump", "ramses", "kairo", "meteora"})

    def test_offline_falls_back_to_stale_cache(self):
        os.utime(os.path.join(self.dir, "cache", "projects.json"), (0, 0))
        self.assertEqual(len(tracker.curated(url="http://127.0.0.1:9/none.json")), 4)

    def test_pick_and_cap(self):
        tracker.pick(self.cfg, ["pump", "ramses"])
        self.assertEqual([p["id"] for p in tracker.selected(self.cfg)], ["pump", "ramses"])
        with self.assertRaises(SystemExit):
            tracker.pick(self.cfg, ["nope"])
        self.cfg["projects"] = [{"id": f"x{i}"} for i in range(tracker.MAX_PROJECTS)]
        with self.assertRaises(SystemExit):
            tracker.pick(self.cfg, ["kairo"])

    def test_own_project(self):
        rec = tracker.add_own(self.cfg, dict(OWN))
        self.assertEqual(rec["id"], "own-my-token")
        self.assertEqual(rec["x_project"], "mytoken")
        sel = tracker.selected(self.cfg)
        self.assertTrue(sel[0]["own"])
        tracker.remove(self.cfg, rec["id"], delete_own=True)
        self.assertEqual(tracker.own_projects(), [])
        with self.assertRaises(SystemExit):
            tracker.add_own(self.cfg, {"name": "x"})

    def test_set_key(self):
        tracker.set_key(self.cfg, "daily.time", "07:30")
        tracker.set_key(self.cfg, "community.enabled", "false")
        self.assertEqual(self.cfg["daily"]["time"], "07:30")
        self.assertIs(self.cfg["community"]["enabled"], False)
        with self.assertRaises(SystemExit):
            tracker.set_key(self.cfg, "format", "fancy")

    def test_plan(self):
        tracker.pick(self.cfg, ["pump", "ramses"])
        now = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
        p = tracker.plan(self.cfg, now=now)
        self.assertEqual(p["start_time"], "2026-10-26T08:00:00Z")
        self.assertIn("from:Pumpfun", p["official_queries"][0])
        self.assertIn("from:D333z", p["official_queries"][0])
        self.assertEqual(len(p["cashtag_scans"]), 2)
        self.assertEqual(tracker.plan(self.cfg, weekly=True, now=now)["start_time"], "2026-10-20T08:00:00Z")

    def test_batches(self):
        qs = tracker.batch_queries([f"h{i}" for i in range(20)])
        self.assertEqual(len(qs), 3)
        self.assertTrue(all(q.startswith("(from:") and q.endswith(") -is:retweet") for q in qs))

    def test_render_and_recent(self):
        tracker.pick(self.cfg, ["pump", "ramses", "kairo"])
        with open(os.path.join(self.dir, "last_prices.json"), "w") as fh:
            json.dump([{"project_id": "pump", "price_usd": 0.0055, "mcap_usd": 1.95e9, "change_24h": 1.2,
                        "change_7d": None, "liquidity_usd": 9e7},
                       {"project_id": "ramses", "price_usd": 0.03, "mcap_usd": 2.6e6, "change_24h": -1,
                        "change_7d": None, "liquidity_usd": 3.8e5}], fh)
        items = [{"id": "ramses", "paragraphs": [{"text": "Zaps are live.", "sources": [{"handle": "RamsesExchange", "id": "1"}]}]},
                 {"id": "pump", "paragraphs": [{"text": "Buybacks hit $1,500,000.", "sources": [{"handle": "Pumpfun", "id": "2"}]}]}]
        now = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
        out = tracker.render(self.cfg, items, now=now)
        self.assertLess(out.index("@Pumpfun - $PUMP - $1.95B"), out.index("@RamsesExchange"))
        self.assertIn("Buybacks hit $1.5M.", out)
        self.assertIn("No news in the window: @", out)
        weekly = tracker.render(self.cfg, items, weekly=True, now=now)
        self.assertTrue(weekly.startswith("Weekly builder overview"))
        self.assertTrue(weekly.rstrip().endswith("made by @winiam4444"))
        self.assertEqual(len(tracker.recent()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
