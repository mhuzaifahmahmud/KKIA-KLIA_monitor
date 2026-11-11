#!/usr/bin/env python3
"""Developer helper: write SYNTHETIC price history into a project copy so analyze/alert/dashboard can be tried.

Usage: MONITOR_ROOT=/tmp/copy python tests/simulate.py [days]
The numbers are invented (a staircase that mimics fare tiers selling out). Never run this in the real repo.
"""
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import common as c  # noqa: E402

days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
cfg = c.load_config()
random.seed(7)
today = c.local_now(cfg).date()
rows, ins = [], []
for w in cfg["watch"]:
    travel = date.fromisoformat(w["date"])
    base = random.choice([180, 205, 230])
    price = base
    for i in range(days, 0, -1):
        d = today - timedelta(days=i - 1)
        if random.random() < 0.18:
            price += random.choice([-25, 20, 26, 35, 45])  # tier step
        price = max(120, price)
        for airline, fn, dep, add in (("AirAsia", "AK 5101", "07:30", 0), ("Malaysia Airlines", "MH 2605", "09:15", 74)):
            rows.append({
                "check_date": d.isoformat(), "check_time_utc": d.isoformat() + "T02:30:00Z",
                "route": w["label"], "origin": w["from"], "destination": w["to"],
                "travel_date": w["date"], "days_to_departure": (travel - d).days,
                "airline": airline, "flight_no": fn, "dep_time": dep, "stops": 0,
                "price": price + add, "currency": "MYR", "source": "SYNTHETIC TEST DATA",
            })
        ins.append({"check_date": d.isoformat(), "route": w["label"], "travel_date": w["date"],
                    "price_level": "typical", "lowest_price": price, "typical_low": base - 20, "typical_high": base + 110})
c.append_csv(c.DATA / "prices.csv", c.PRICE_FIELDS, rows)
c.append_csv(c.DATA / "insights.csv", c.INSIGHT_FIELDS, ins)
print(f"wrote {len(rows)} synthetic rows for {len(cfg['watch'])} watches over {days} days")
