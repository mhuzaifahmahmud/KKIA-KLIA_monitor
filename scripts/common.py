"""Shared helpers: paths, config, CSV/JSON I/O, Malaysia-time stamps."""
import csv
import json
import os
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# MONITOR_ROOT lets the tests run against a temporary copy of the project.
ROOT = Path(os.environ.get("MONITOR_ROOT") or Path(__file__).resolve().parent.parent)
DATA = ROOT / "data"
DOCS_DATA = ROOT / "docs" / "data"

PRICE_FIELDS = [
    "check_date", "check_time_utc", "route", "origin", "destination",
    "travel_date", "days_to_departure", "airline", "flight_no", "dep_time",
    "stops", "price", "currency", "source",
]
INSIGHT_FIELDS = [
    "check_date", "route", "travel_date", "price_level",
    "lowest_price", "typical_low", "typical_high",
]


def expand_ranges(cfg):
    """Turn every [[range]] block into one watch per travel date, and merge them into cfg["watch"].

    [[range]] label/from/to + start/end (inclusive) + step_days (default 1).
    Explicit [[watch]] entries are kept; a duplicate label+date is only watched once.
    """
    watches = list(cfg.get("watch", []))
    seen = {(w["label"], w["date"]) for w in watches}
    for r in cfg.get("range", []):
        step = max(1, int(r.get("step_days", 1)))
        day, end = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
        while day <= end:
            key = (r["label"], day.isoformat())
            if key not in seen:
                seen.add(key)
                watches.append({"label": r["label"], "from": r["from"], "to": r["to"], "date": day.isoformat()})
            day += timedelta(days=step)
    cfg["watch"] = watches
    return cfg


def load_config(path=None):
    p = Path(path) if path else ROOT / "config.toml"
    with open(p, "rb") as f:
        return expand_ranges(tomllib.load(f))


def local_now(cfg):
    off = cfg.get("settings", {}).get("timezone_offset_hours", 8)
    return datetime.now(timezone.utc) + timedelta(hours=off)


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            w.writeheader()
        w.writerows(rows)


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def watch_key(label, travel_date):
    return f"{label}|{travel_date}"
