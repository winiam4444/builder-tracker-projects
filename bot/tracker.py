"""Builder Tracker command line. Python 3.9+ stdlib only.

Everything the bot needs between X reads: settings, project selection, own projects, X query plan,
cashtag filtering, prices and the final layout. User data lives in STATE (default
/workspace/builder-tracker/state, override with BUILDER_TRACKER_STATE).

    python3 tracker.py config show | init | set KEY VALUE        (KEY like daily.time, tone, format)
    python3 tracker.py projects [--refresh]                      selected projects with sources
    python3 tracker.py search --query pump --chain solana        find curated projects
    python3 tracker.py own list | add JSON | remove ID
    python3 tracker.py pick add ID [ID ...] | remove ID | clear  choose projects (max 25)
    python3 tracker.py plan [--weekly]                           X queries to run, with window
    python3 tracker.py filter --project ID --file RESPONSE.json  clean a cashtag search response
    python3 tracker.py prices                                    live prices, saves last_prices.json
    python3 tracker.py render --input ITEMS.json [--weekly]      final text, saved to updates/
    python3 tracker.py recent [--days 7]                         earlier updates, for dedupe
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cashtag  # noqa: E402
import format as fmt  # noqa: E402
import prices  # noqa: E402

PROJECTS_URL = "https://raw.githubusercontent.com/winiam4444/builder-tracker-projects/main/projects.json"
MAX_PROJECTS = 25
SOURCE_KEYS = ["project", "founders", "team", "notable", "competitors", "cashtags"]
DEFAULT_SOURCES = {"project": True, "founders": True, "team": True, "notable": True,
                   "competitors": False, "cashtags": True}
OWN_FIELDS = ["name", "ticker", "chain", "contract_address", "x_project"]


def state_dir() -> str:
    d = os.environ.get("BUILDER_TRACKER_STATE", "/workspace/builder-tracker/state")
    os.makedirs(d, exist_ok=True)
    return d


def sp(*parts) -> str:
    return os.path.join(state_dir(), *parts)


def _read(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


# ---------- config ----------

def default_config() -> dict:
    with open(os.path.join(HERE, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["projects"] = []
    return cfg


def load_config() -> dict:
    cfg = _read(sp("config.json"), None)
    if cfg is None:
        raise SystemExit("No config yet: run the builder-tracker-getting-started skill first.")
    return cfg


def save_config(cfg: dict):
    _write(sp("config.json"), cfg)


def set_key(cfg: dict, key: str, value: str):
    try:
        val = json.loads(value)
    except json.JSONDecodeError:
        val = value
    node = cfg
    parts = key.split(".")
    for k in parts[:-1]:
        node = node.setdefault(k, {})
    node[parts[-1]] = val
    if key == "format" and val not in ("plain", "emoji"):
        raise SystemExit("format is plain or emoji")
    if key == "tone" and val not in ("standard", "casual", "detailed"):
        raise SystemExit("tone is standard, casual or detailed")


# ---------- project list ----------

def curated(refresh: bool = False, url: str = PROJECTS_URL) -> list[dict]:
    """The public list, cached for a day in STATE/cache. Falls back to the cache when offline."""
    cache = sp("cache", "projects.json")
    fresh = os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86_400
    if refresh or not fresh:
        try:
            data = prices.http_json(url)
            if isinstance(data, list) and data:
                _write(cache, data)
        except Exception as e:  # noqa: BLE001
            if not os.path.exists(cache):
                raise SystemExit(f"Could not download the project list: {e}")
    return _read(cache, [])


def own_projects() -> list[dict]:
    return _read(sp("own_projects.json"), [])


def all_projects(refresh=False) -> dict[str, dict]:
    out = {p["id"]: dict(p, own=False) for p in curated(refresh) if p.get("status", "active") == "active"}
    for p in own_projects():
        out[p["id"]] = dict(p, own=True)
    return out


def selected(cfg: dict, refresh=False) -> list[dict]:
    pool = all_projects(refresh)
    out, missing = [], []
    for row in cfg.get("projects", []):
        p = pool.get(row["id"])
        if not p:
            missing.append(row["id"])
            continue
        out.append(dict(p, sources={**DEFAULT_SOURCES, **row.get("sources", {})}))
    if missing:
        print(json.dumps({"warning": "not in the list any more", "ids": missing}), file=sys.stderr)
    return out


def pick(cfg: dict, ids: list[str], sources: dict | None = None):
    pool = all_projects()
    have = {r["id"] for r in cfg.setdefault("projects", [])}
    for i in ids:
        if i not in pool:
            raise SystemExit(f"Unknown project id: {i}")
        if i in have:
            continue
        if len(cfg["projects"]) >= MAX_PROJECTS:
            raise SystemExit(f"Max {MAX_PROJECTS} projects. Remove one first.")
        cfg["projects"].append({"id": i, "sources": dict(sources or DEFAULT_SOURCES)})
        have.add(i)


def add_own(cfg: dict, rec: dict) -> dict:
    lacking = [k for k in OWN_FIELDS if not rec.get(k)]
    if lacking:
        raise SystemExit("Own project needs: " + ", ".join(lacking))
    if rec["chain"] not in ("solana", "robinhood", "arc") and not rec.get("allow_other_chain"):
        print(json.dumps({"warning": "chain not in the curated set; prices use DexScreener chain ids"}), file=sys.stderr)
    rec = {"x_founders": [], "x_team": [], "x_notable": [], "competitors": [], "category": [],
           "coingecko_id": "", "status": "active", "products": [], **rec}
    rec["x_project"] = rec["x_project"].lstrip("@")
    rec["id"] = rec.get("id") or "own-" + "".join(c if c.isalnum() else "-" for c in rec["name"].lower()).strip("-")
    rec["added"] = rec.get("added") or datetime.now(timezone.utc).date().isoformat()
    own = [p for p in own_projects() if p["id"] != rec["id"]]
    own.append(rec)
    if rec["id"] not in {r["id"] for r in cfg["projects"]} and len(cfg["projects"]) >= MAX_PROJECTS:
        raise SystemExit(f"Max {MAX_PROJECTS} projects. Remove one first.")
    _write(sp("own_projects.json"), own)
    pick(cfg, [rec["id"]], rec.pop("sources", None))
    return rec


def remove(cfg: dict, pid: str, delete_own=False):
    cfg["projects"] = [r for r in cfg.get("projects", []) if r["id"] != pid]
    if delete_own:
        _write(sp("own_projects.json"), [p for p in own_projects() if p["id"] != pid])


# ---------- X plan ----------

def window(cfg: dict, weekly=False, now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    hours = 24 * 7 if weekly else cfg.get("daily", {}).get("window_hours", 24)
    start = now - timedelta(hours=hours)
    f = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(f), now.strftime(f)


def handles_for(p: dict, pool: dict[str, dict]) -> list[str]:
    s = p["sources"]
    hs = []
    if s.get("project"):
        hs.append(p["x_project"])
    for key, field in (("founders", "x_founders"), ("team", "x_team"), ("notable", "x_notable")):
        if s.get(key):
            hs += p.get(field, [])
    if s.get("competitors"):
        hs += [pool[c]["x_project"] for c in p.get("competitors", []) if c in pool]
    return list(dict.fromkeys(h.lstrip("@") for h in hs if h))


def _from_query(hs: list[str]) -> str:
    return "(" + " OR ".join(f"from:{x}" for x in hs) + ") -is:retweet"


def batch_queries(handles: list[str], max_len: int = 900, per: int = 8) -> list[str]:
    """Group handles into from:-queries (8 per call). Parentheses keep -is:retweet on every handle."""
    out, cur = [], []
    for h in handles:
        trial = cur + [h]
        if len(trial) > per or len(_from_query(trial)) > max_len:
            out.append(_from_query(cur))
            cur = [h]
        else:
            cur = trial
    if cur:
        out.append(_from_query(cur))
    return out


def plan(cfg: dict, weekly=False, now=None) -> dict:
    projs = selected(cfg)
    pool = all_projects()
    start, end = window(cfg, weekly, now)
    owner = {}
    for p in projs:
        for h in handles_for(p, pool):
            owner.setdefault(h.lower(), []).append(p["id"])
    excl = cfg.get("community", {}).get("exclude_handles", [])
    lang = cfg.get("community", {}).get("lang", "en") or None
    scans = [{"project": p["id"], "queries": cashtag.build_queries(p, excl, lang)}
             for p in projs if p["sources"].get("cashtags") and cfg.get("community", {}).get("enabled", True)]
    official = batch_queries(list(dict.fromkeys(h for p in projs for h in handles_for(p, pool))))
    return {"start_time": start, "end_time": end, "official_queries": official,
            "handle_to_projects": owner, "cashtag_scans": scans,
            "estimated_calls": {"official": len(official), "cashtag_min": len(scans), "cashtag_max": 2 * len(scans)}}


# ---------- render ----------

def render(cfg: dict, items_in: list[dict], weekly=False, now=None) -> str:
    """items_in: [{"id", "paragraphs": [{"text","sources"}], "community": {"text","sources"} | null}]"""
    projs = {p["id"]: p for p in selected(cfg)}
    last = {r["project_id"]: r for r in _read(sp("last_prices.json"), [])}
    given = {i["id"]: i for i in items_in}
    items = []
    for pid, p in projs.items():
        it = given.get(pid, {})
        items.append((p, last.get(pid) if cfg.get("prices", {}).get("show_price_line", True) else None,
                      it.get("paragraphs", []), it.get("community")))
    tz = _tz(cfg.get("timezone", "UTC"))
    when = (now or datetime.now(timezone.utc)).astimezone(tz)
    if weekly:
        text = fmt.daily_update(items, when, cfg.get("format", "plain"), window="last 7 days",
                                title="Weekly builder overview", footer=fmt.weekly_footer())
    else:
        text = fmt.daily_update(items, when, cfg.get("format", "plain"))
    if not cfg.get("daily", {}).get("show_quiet_projects", True):
        text = "\n\n".join(b for b in text.split("\n\n") if not b.startswith("No news in the window")) + "\n"
    name = when.strftime("%Y-%m-%d") + ("-weekly" if weekly else "") + ".md"
    os.makedirs(sp("updates"), exist_ok=True)
    with open(sp("updates", name), "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def _tz(name: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return timezone.utc


def recent(days=7) -> list[str]:
    d = sp("updates")
    if not os.path.isdir(d):
        return []
    cutoff = time.time() - days * 86_400
    return sorted(os.path.join(d, f) for f in os.listdir(d) if os.path.getmtime(os.path.join(d, f)) >= cutoff)


# ---------- CLI ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Builder Tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config")
    c.add_argument("action", choices=["show", "init", "set"])
    c.add_argument("key", nargs="?")
    c.add_argument("value", nargs="?")
    pr = sub.add_parser("projects")
    pr.add_argument("--refresh", action="store_true")
    se = sub.add_parser("search")
    se.add_argument("--query", default="")
    se.add_argument("--chain")
    se.add_argument("--category")
    o = sub.add_parser("own")
    o.add_argument("action", choices=["list", "add", "remove"])
    o.add_argument("arg", nargs="?")
    pk = sub.add_parser("pick")
    pk.add_argument("action", choices=["add", "remove", "clear", "sources"])
    pk.add_argument("ids", nargs="*")
    pk.add_argument("--sources", help='JSON, e.g. {"competitors": true}')
    pl = sub.add_parser("plan")
    pl.add_argument("--weekly", action="store_true")
    fi = sub.add_parser("filter")
    fi.add_argument("--project", required=True)
    fi.add_argument("--file", required=True)
    sub.add_parser("prices")
    r = sub.add_parser("render")
    r.add_argument("--input", required=True)
    r.add_argument("--weekly", action="store_true")
    rc = sub.add_parser("recent")
    rc.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    out = None

    if a.cmd == "config":
        if a.action == "init":
            cfg = _read(sp("config.json"), None) or default_config()
            save_config(cfg)
        else:
            cfg = load_config()
            if a.action == "set":
                set_key(cfg, a.key, a.value)
                save_config(cfg)
        out = cfg
    elif a.cmd == "projects":
        out = selected(load_config(), a.refresh)
    elif a.cmd == "search":
        q = a.query.lower()
        out = [{k: p.get(k) for k in ("id", "name", "ticker", "chain", "category", "x_project")}
               for p in curated() if p.get("status", "active") == "active"
               and (not q or q in p["name"].lower() or q == p["ticker"].lower() or q in p["x_project"].lower())
               and (not a.chain or p["chain"] == a.chain)
               and (not a.category or a.category.lower() in [c.lower() for c in p.get("category", [])])]
    elif a.cmd == "own":
        cfg = load_config()
        if a.action == "list":
            out = own_projects()
        elif a.action == "add":
            out = add_own(cfg, json.loads(a.arg))
            save_config(cfg)
        else:
            remove(cfg, a.arg, delete_own=True)
            save_config(cfg)
            out = {"removed": a.arg}
    elif a.cmd == "pick":
        cfg = load_config()
        src = json.loads(a.sources) if a.sources else None
        if a.action == "add":
            pick(cfg, a.ids, {**DEFAULT_SOURCES, **(src or {})})
        elif a.action == "remove":
            for i in a.ids:
                remove(cfg, i)
        elif a.action == "clear":
            cfg["projects"] = []
        elif a.action == "sources":
            for row in cfg["projects"]:
                if not a.ids or row["id"] in a.ids:
                    row["sources"] = {**DEFAULT_SOURCES, **row.get("sources", {}), **(src or {})}
        save_config(cfg)
        out = {"projects": cfg["projects"], "count": len(cfg["projects"]), "max": MAX_PROJECTS}
    elif a.cmd == "plan":
        out = plan(load_config(), a.weekly)
    elif a.cmd == "filter":
        cfg = load_config()
        p = all_projects()[a.project]
        with open(a.file, encoding="utf-8") as fh:
            resp = json.load(fh)
        com = cfg.get("community", {})
        out = cashtag.filter_posts(resp, p, com.get("exclude_handles", []), com.get("min_followers", 50))
        out = [{"id": x["id"], "username": x["username"], "score": cashtag.score(x), "text": x["text"],
                "url": f"https://x.com/{x['username']}/status/{x['id']}"} for x in out]
    elif a.cmd == "prices":
        cfg = load_config()
        res = prices.get_prices(selected(cfg), cfg.get("prices", {}).get("min_liquidity_usd", prices.MIN_LIQUIDITY_USD),
                                sp("price_history.json"))
        out = [asdict(x) for x in res]
        _write(sp("last_prices.json"), out)
    elif a.cmd == "render":
        with open(a.input, encoding="utf-8") as fh:
            items = json.load(fh)
        print(render(load_config(), items, a.weekly), end="")
        return
    elif a.cmd == "recent":
        out = recent(a.days)
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
