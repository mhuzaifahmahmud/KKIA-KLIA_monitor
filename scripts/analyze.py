#!/usr/bin/env python3
"""Turn data/prices.csv into docs/data/summary.json: stats, price steps and a wait/book signal.

The signal is a transparent rule set, not a trained model. Rules, in order:
  1. 7 days or fewer to departure            -> BOOK NOW
  2. Google rates the price "low"            -> BOOK NOW
  3. cheapest price seen so far (3+ checks)  -> BOOK NOW
  4. 21 days or fewer to departure           -> BOOK SOON
  5. with enough history (min_history_for_model checks):
       in the cheapest fifth of its own history -> BOOK SOON
       rising 0.5 percent a day or faster       -> BOOK SOON
       otherwise                                -> WAIT
  6. Google rates the price "high"           -> WAIT
  7. otherwise                               -> WATCH (still collecting history)
"""
import shutil
import sys
from datetime import date

import common as c


def slope(points):
    """Least-squares slope (price change per day) over [(day_number, price), ...]."""
    n = len(points)
    if n < 3:
        return 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / den if den else 0.0


def build_item(w, price_rows, insight_rows, google_hist, cfg, today):
    label, travel = w["label"], w["date"]
    rows = [r for r in price_rows if r["route"] == label and r["travel_date"] == travel]
    by_day = {}
    for r in rows:
        by_day.setdefault(r["check_date"], []).append(r)

    series = []  # one cheapest price per check day
    for day in sorted(by_day):
        best = min(by_day[day], key=lambda r: float(r["price"]))
        series.append((day, float(best["price"]), best["airline"]))

    item = {
        "label": label, "from": w["from"], "to": w["to"], "travel_date": travel,
        "days_to_departure": (date.fromisoformat(travel) - today).days,
        "checks": len(series), "latest": None, "previous_price": None,
        "change_vs_prev": None, "first_price": None, "change_vs_first": None,
        "low": None, "high": None, "series": [], "offers": [],
        "insight": None, "google_history": google_hist or [],
        "stats": {"rises": 0, "drops": 0, "unchanged": 0, "avg_rise": None,
                  "avg_drop": None, "rise_share": None},
        "signal": "WATCH", "reasons": [], "forecast": {"expected_7d": None, "confidence": "low"},
    }
    if not series:
        item["reasons"] = ["No data yet. The first daily check will fill this in."]
        return item

    prices = [p for _, p, _ in series]
    latest_day = series[-1][0]
    latest_offers = sorted(by_day[latest_day], key=lambda r: float(r["price"]))
    item["latest"] = {
        "date": latest_day, "price": prices[-1], "airline": series[-1][2],
        "flight_no": latest_offers[0]["flight_no"], "dep_time": latest_offers[0]["dep_time"],
    }
    item["offers"] = [{
        "airline": r["airline"], "flight_no": r["flight_no"],
        "dep_time": r["dep_time"], "price": float(r["price"]),
    } for r in latest_offers[:12]]
    item["series"] = [[d, p] for d, p, _ in series]
    item["first_price"] = prices[0]
    item["low"], item["high"] = min(prices), max(prices)
    item["change_vs_first"] = round(prices[-1] - prices[0], 2)
    if len(prices) > 1:
        item["previous_price"] = prices[-2]
        item["change_vs_prev"] = round(prices[-1] - prices[-2], 2)
        diffs = [b - a for a, b in zip(prices, prices[1:])]
        rises = [d for d in diffs if d > 0]
        drops = [d for d in diffs if d < 0]
        item["stats"] = {
            "rises": len(rises), "drops": len(drops), "unchanged": len(diffs) - len(rises) - len(drops),
            "avg_rise": round(sum(rises) / len(rises), 2) if rises else None,
            "avg_drop": round(sum(drops) / len(drops), 2) if drops else None,
            "rise_share": round(len(rises) / len(diffs), 3),
        }

    ins = [r for r in insight_rows if r["route"] == label and r["travel_date"] == travel]
    if ins:
        last = ins[-1]
        item["insight"] = {
            "price_level": last["price_level"], "lowest_price": last["lowest_price"],
            "typical_low": last["typical_low"], "typical_high": last["typical_high"],
        }

    judge(item, prices, series, cfg)
    return item


def judge(item, prices, series, cfg):
    min_hist = int(cfg.get("settings", {}).get("min_history_for_model", 14))
    n, cur, days = len(prices), prices[-1], item["days_to_departure"]
    ins = item["insight"] or {}
    level = (ins.get("price_level") or "").lower()
    at_low = n >= 3 and cur <= min(prices) and max(prices) > min(prices)
    signal, reasons = "WATCH", []

    if days <= 7:
        signal = "BOOK NOW"
        reasons.append(f"Only {days} days to departure, little time left to wait.")
    elif level == "low":
        signal = "BOOK NOW"
        reasons.append("Google rates this price as low for the route.")
    elif at_low:
        signal = "BOOK NOW"
        reasons.append("Lowest price seen since monitoring started.")
    elif days <= 21:
        signal = "BOOK SOON"
        reasons.append("Inside 3 weeks of departure, when waiting gets riskier.")
    elif n >= min_hist:
        points = [(date.fromisoformat(d).toordinal(), p) for d, p, _ in series[-10:]]
        sl = slope(points)
        below = sum(1 for p in prices if p < cur) / n
        # straight-line projection, capped at +/-20% so a few big tier jumps cannot give a silly number
        item["forecast"]["expected_7d"] = round(max(cur * 0.8, min(cur * 1.2, cur + sl * 7)))
        item["forecast"]["confidence"] = "medium" if n >= 28 else "low"
        if below <= 0.2:
            signal = "BOOK SOON"
            reasons.append("Price is in the cheapest fifth of its own history.")
        elif sl >= 0.005 * cur:
            signal = "BOOK SOON"
            reasons.append(f"Price is rising about RM {sl:.0f} a day.")
        else:
            signal = "WAIT"
            reasons.append("No rising trend and the price is not unusually low.")
    elif level == "high":
        signal = "WAIT"
        reasons.append("Google rates this price as high for the route.")
    else:
        reasons.append(f"Still collecting history ({n} of {min_hist} daily checks needed for the trend rule).")

    if level and "Google" not in " ".join(reasons):
        extra = f"Google rates this price as {level}"
        if ins.get("typical_low") and ins.get("typical_high"):
            extra += f" (typical RM {ins['typical_low']} to {ins['typical_high']})"
        reasons.append(extra + ".")
    item["signal"], item["reasons"] = signal, reasons


def main():
    cfg = c.load_config()
    today = c.local_now(cfg).date()
    price_rows = c.read_csv(c.DATA / "prices.csv")
    insight_rows = c.read_csv(c.DATA / "insights.csv")
    google_hist = c.read_json(c.DATA / "google_history.json", {})
    usage = c.read_json(c.DATA / "usage.json", {"month": "", "searches": 0})

    items = []
    for w in cfg.get("watch", []):
        if date.fromisoformat(w["date"]) < today:
            continue  # trip date has passed; keep the history in the CSV but drop it from the dashboard
        items.append(build_item(w, price_rows, insight_rows,
                                google_hist.get(c.watch_key(w["label"], w["date"])), cfg, today))

    summary = {
        "updated": c.local_now(cfg).strftime("%Y-%m-%d %H:%M") + " Malaysia time",
        "currency": cfg.get("settings", {}).get("currency", "MYR"),
        "min_history": int(cfg.get("settings", {}).get("min_history_for_model", 14)),
        "searches_used": usage.get("searches", 0),
        "search_limit": int(cfg.get("settings", {}).get("monthly_search_limit", 240)),
        "items": items,
    }
    c.write_json(c.DOCS_DATA / "summary.json", summary)
    src = c.DATA / "prices.csv"
    if src.exists():
        shutil.copyfile(src, c.DOCS_DATA / "prices.csv")
    print(f"summary written: {len(items)} watch items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
