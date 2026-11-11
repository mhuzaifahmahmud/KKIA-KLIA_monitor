#!/usr/bin/env python3
"""Fetch today's Google Flights prices (through SerpApi) for every [[watch]] in config.toml.

Polite by design:
  * one search per route+date per day, never repeated on the same day (use --force to override)
  * searches run one at a time with a pause between them
  * a monthly search budget is enforced (default 240, inside SerpApi's 250 free searches)
  * on HTTP 401/403/429 or "out of searches" it stops immediately and does not retry
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

import common as c

API = "https://serpapi.com/search.json"
UA = "kk-flight-monitor/1.0 (personal price log; one search per route and date per day)"


class StopAll(Exception):
    """Raised when continuing would be impolite or pointless (quota, auth, rate limit)."""


def parse_offers(js):
    """Flatten best_flights + other_flights into simple dicts."""
    offers = []
    for group in ("best_flights", "other_flights"):
        for item in js.get(group) or []:
            legs = item.get("flights") or []
            price = item.get("price")
            if not legs or price is None:
                continue
            dep = (legs[0].get("departure_airport") or {}).get("time", "") or ""
            airlines = []
            for leg in legs:
                name = leg.get("airline")
                if name and name not in airlines:
                    airlines.append(name)
            numbers = [str(leg["flight_number"]).strip() for leg in legs if leg.get("flight_number")]
            offers.append({
                "airline": " + ".join(airlines) or "Unknown",
                "flight_no": " + ".join(numbers),
                "dep_time": dep[11:16] if len(dep) >= 16 else "",
                "stops": len(legs) - 1,
                "price": price,
            })
    return offers


def parse_insights(js):
    pi = js.get("price_insights") or {}
    rng = pi.get("typical_price_range") or []
    return {
        "price_level": pi.get("price_level") or "",
        "lowest_price": pi.get("lowest_price"),
        "typical_low": rng[0] if len(rng) > 0 else None,
        "typical_high": rng[1] if len(rng) > 1 else None,
        "history": pi.get("price_history") or [],
    }


def history_pairs(history):
    """Google's own sparse price history -> [[YYYY-MM-DD, price], ...]."""
    pairs = []
    for item in history:
        try:
            ts, price = float(item[0]), item[1]
            if ts > 1e11:  # milliseconds
                ts /= 1000.0
            day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
            pairs.append([day, price])
        except (TypeError, ValueError, IndexError, OSError):
            continue
    return pairs


def search(watch, cfg, key):
    s = cfg.get("settings", {})
    params = {
        "engine": "google_flights",
        "departure_id": watch["from"],
        "arrival_id": watch["to"],
        "outbound_date": watch["date"],
        "type": "2",  # one-way
        "currency": s.get("currency", "MYR"),
        "hl": "en",
        "gl": s.get("country", "my"),
        "api_key": key,
    }
    if s.get("nonstop_only", True):
        params["stops"] = "1"  # 1 = nonstop only
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise StopAll(f"SerpApi answered HTTP {e.code}; stopping without retrying")
            if attempt == 2 or e.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(30)  # one gentle retry for temporary server trouble


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to config.toml (default: project root)")
    ap.add_argument("--mock", help="JSON file to use instead of calling the API (for testing)")
    ap.add_argument("--force", action="store_true", help="search again even if today's data exists")
    args = ap.parse_args()

    cfg = c.load_config(args.config)
    s = cfg.get("settings", {})
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if not key and not args.mock:
        print("ERROR: SERPAPI_KEY is not set (add it as a GitHub secret).")
        return 2

    now = c.local_now(cfg)
    today = now.date()
    month = now.strftime("%Y-%m")
    usage = c.read_json(c.DATA / "usage.json", {})
    if usage.get("month") != month:
        usage = {"month": month, "searches": 0}
    limit = int(s.get("monthly_search_limit", 240))
    delay = float(s.get("request_delay_seconds", 5))

    existing = c.read_csv(c.DATA / "prices.csv")
    done = {(r["check_date"], r["route"], r["travel_date"]) for r in existing}
    google_history = c.read_json(c.DATA / "google_history.json", {})

    # SerpApi is only the backup source: with many watched dates, search just a few spread-out ones per run
    # so the free monthly searches last. (Skipped when testing with --mock.)
    pending = [w for w in cfg.get("watch", [])
               if date.fromisoformat(w["date"]) >= today
               and (today.isoformat(), w["label"], w["date"]) not in done]
    cap = int(s.get("serpapi_daily_max", 6))
    allowed = None
    if not args.mock and not args.force and len(pending) > cap > 0:
        step = len(pending) / cap
        allowed = {id(pending[int(i * step)]) for i in range(cap)}
        print(f"note   {len(pending)} dates are missing today; searching {cap} spread-out ones "
              f"(serpapi_daily_max) to protect the monthly limit")

    ok = failed = skipped = 0
    first = True
    for w in cfg.get("watch", []):
        label, travel = w["label"], w["date"]
        if allowed is not None and id(w) not in allowed and date.fromisoformat(travel) >= today \
                and (today.isoformat(), label, travel) not in done:
            continue
        if date.fromisoformat(travel) < today:
            print(f"skip   {label} {travel}: travel date has passed")
            skipped += 1
            continue
        if (today.isoformat(), label, travel) in done and not args.force:
            print(f"skip   {label} {travel}: already recorded today")
            skipped += 1
            continue
        if not args.mock and usage["searches"] >= limit:
            print(f"STOP   monthly search limit reached ({usage['searches']}/{limit})")
            break
        if not first and not args.mock:
            time.sleep(delay)
        first = False

        try:
            if args.mock:
                with open(args.mock, encoding="utf-8") as f:
                    js = json.load(f)
            else:
                usage["searches"] += 1  # counted before the call: failed calls may count too
                js = search(w, cfg, key)
        except StopAll as e:
            print(f"STOP   {e}")
            failed += 1
            break
        except Exception as e:  # network or server trouble: log and carry on with the next watch
            print(f"ERROR  {label} {travel}: {e}")
            failed += 1
            continue

        offers = parse_offers(js)
        err = js.get("error")
        if err and not offers:
            low = str(err).lower()
            print(f"ERROR  {label} {travel}: {err}")
            failed += 1
            if "run out" in low or "invalid api key" in low:
                break
            continue

        days_left = (date.fromisoformat(travel) - today).days
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [{
            "check_date": today.isoformat(), "check_time_utc": stamp, "route": label,
            "origin": w["from"], "destination": w["to"], "travel_date": travel,
            "days_to_departure": days_left, "airline": o["airline"], "flight_no": o["flight_no"],
            "dep_time": o["dep_time"], "stops": o["stops"], "price": o["price"],
            "currency": s.get("currency", "MYR"), "source": "Google Flights via SerpApi",
        } for o in offers]
        c.append_csv(c.DATA / "prices.csv", c.PRICE_FIELDS, rows)

        ins = parse_insights(js)
        c.append_csv(c.DATA / "insights.csv", c.INSIGHT_FIELDS, [{
            "check_date": today.isoformat(), "route": label, "travel_date": travel,
            "price_level": ins["price_level"], "lowest_price": ins["lowest_price"],
            "typical_low": ins["typical_low"], "typical_high": ins["typical_high"],
        }])
        pairs = history_pairs(ins["history"])
        if pairs:
            google_history[c.watch_key(label, travel)] = pairs

        cheapest = min((o["price"] for o in offers), default=None)
        print(f"ok     {label} {travel}: {len(offers)} flights, cheapest {cheapest}")
        ok += 1

    if not args.mock:
        c.write_json(c.DATA / "usage.json", usage)
    c.write_json(c.DATA / "google_history.json", google_history)
    print(f"done: {ok} recorded, {skipped} skipped, {failed} failed; searches this month {usage['searches']}/{limit}")
    return 1 if (failed and not ok) else 0


if __name__ == "__main__":
    sys.exit(main())
