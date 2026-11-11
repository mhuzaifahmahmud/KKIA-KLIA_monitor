"""Offline tests: run with  python -m unittest discover -s tests -v   (from the project root)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

import analyze  # noqa: E402
import fetch  # noqa: E402

FIXTURE = PROJECT / "tests" / "fixtures" / "serpapi_sample.json"


def make_root():
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(PROJECT / "config.toml", tmp / "config.toml")
    # push the example dates into the future so the tests do not depend on today's date
    text = (tmp / "config.toml").read_text()
    future = (date.today() + timedelta(days=90)).isoformat()
    for old in ("2026-12-20", "2026-12-27"):
        text = text.replace(old, future)
    (tmp / "config.toml").write_text(text)
    return tmp


def run(script, root, *args):
    env = dict(os.environ, MONITOR_ROOT=str(root))
    env.pop("NTFY_TOPIC", None)
    return subprocess.run([sys.executable, str(PROJECT / "scripts" / script), *args],
                          env=env, capture_output=True, text=True)


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.js = json.loads(FIXTURE.read_text())

    def test_offers_flattened(self):
        offers = fetch.parse_offers(self.js)
        self.assertEqual([o["price"] for o in offers], [215, 289, 342])
        self.assertEqual(offers[0]["airline"], "AirAsia")
        self.assertEqual(offers[0]["flight_no"], "AK 5101")
        self.assertEqual(offers[0]["dep_time"], "07:30")
        self.assertEqual(offers[0]["stops"], 0)

    def test_offers_missing_price_skipped(self):
        js = {"best_flights": [{"flights": [{"airline": "X"}]}]}
        self.assertEqual(fetch.parse_offers(js), [])

    def test_insights_and_history(self):
        ins = fetch.parse_insights(self.js)
        self.assertEqual(ins["price_level"], "typical")
        self.assertEqual((ins["typical_low"], ins["typical_high"]), (190, 330))
        pairs = fetch.history_pairs(ins["history"])
        self.assertEqual(len(pairs), 3)
        self.assertRegex(pairs[0][0], r"^\d{4}-\d{2}-\d{2}$")

    def test_history_milliseconds(self):
        pairs = fetch.history_pairs([[1790000000000, 199]])
        self.assertEqual(pairs, fetch.history_pairs([[1790000000, 199]]))


class SignalTests(unittest.TestCase):
    cfg = {"settings": {"min_history_for_model": 14}}

    def item(self, prices, days, level=""):
        start = date.today() - timedelta(days=len(prices))
        series = [((start + timedelta(days=i)).isoformat(), p, "AirAsia") for i, p in enumerate(prices)]
        it = {"days_to_departure": days, "checks": len(prices),
              "insight": {"price_level": level} if level else None,
              "forecast": {"expected_7d": None, "confidence": "low"}}
        analyze.judge(it, prices, series, self.cfg)
        return it

    def test_last_week_is_book_now(self):
        self.assertEqual(self.item([200, 210], 5)["signal"], "BOOK NOW")

    def test_google_low_is_book_now(self):
        self.assertEqual(self.item([200, 210], 60, "low")["signal"], "BOOK NOW")

    def test_new_lowest_is_book_now(self):
        self.assertEqual(self.item([230, 220, 210, 190], 60)["signal"], "BOOK NOW")

    def test_flat_series_is_not_called_lowest(self):
        self.assertEqual(self.item([200, 200, 200], 60)["signal"], "WATCH")

    def test_inside_three_weeks_is_book_soon(self):
        self.assertEqual(self.item([200, 230, 240], 15)["signal"], "BOOK SOON")

    def test_rising_trend_is_book_soon(self):
        prices = [200 + 3 * i for i in range(16)]  # rises about 1.5% a day, not at its low
        self.assertEqual(self.item(prices, 60)["signal"], "BOOK SOON")

    def test_flat_midrange_waits(self):
        prices = [180, 220, 200, 215, 205, 210, 200, 215, 205, 210, 200, 215, 205, 210, 207]
        it = self.item(prices, 60)
        self.assertEqual(it["signal"], "WAIT")
        self.assertIsNotNone(it["forecast"]["expected_7d"])

    def test_google_high_with_little_history_waits(self):
        self.assertEqual(self.item([250, 260], 60, "high")["signal"], "WAIT")

    def test_little_history_watches(self):
        self.assertEqual(self.item([250, 260], 60)["signal"], "WATCH")


class EndToEndTests(unittest.TestCase):
    def test_fetch_analyze_alert_with_mock(self):
        root = make_root()
        r = run("fetch.py", root, "--mock", str(FIXTURE))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok     KK to KUL", r.stdout)
        rows = (root / "data" / "prices.csv").read_text().strip().splitlines()
        self.assertEqual(len(rows), 1 + 4 * 3)  # header + 4 watches x 3 flights

        again = run("fetch.py", root, "--mock", str(FIXTURE))
        self.assertIn("already recorded today", again.stdout)
        self.assertEqual(len((root / "data" / "prices.csv").read_text().strip().splitlines()), len(rows))

        a = run("analyze.py", root)
        self.assertEqual(a.returncode, 0, a.stdout + a.stderr)
        summary = json.loads((root / "docs" / "data" / "summary.json").read_text())
        self.assertEqual(len(summary["items"]), 4)
        first = summary["items"][0]
        self.assertEqual(first["latest"]["price"], 215)
        self.assertEqual(first["checks"], 1)
        self.assertEqual(first["signal"], "WATCH")

        al = run("alert.py", root, "--dry")
        self.assertEqual(al.returncode, 0, al.stdout + al.stderr)

    def test_missing_key_exits_cleanly(self):
        root = make_root()
        env = dict(os.environ, MONITOR_ROOT=str(root))
        env.pop("SERPAPI_KEY", None)
        r = subprocess.run([sys.executable, str(PROJECT / "scripts" / "fetch.py")],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("SERPAPI_KEY", r.stdout)

    def test_alert_drop_and_state(self):
        root = make_root()
        run("fetch.py", root, "--mock", str(FIXTURE))
        # fake an earlier, higher day for the first watch
        import csv
        path = root / "data" / "prices.csv"
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        extra = []
        for off, price in ((3, 260), (2, 250), (1, 245)):
            for r in rows:
                if r["route"] == "KK to KUL" and r["airline"] == "AirAsia":
                    d = dict(r)
                    d["check_date"] = (date.today() - timedelta(days=off)).isoformat()
                    d["price"] = price
                    extra.append(d)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(extra + rows)
        run("analyze.py", root)
        al = run("alert.py", root, "--dry")
        self.assertIn("KK to KUL", al.stdout)
        self.assertIn("down RM", al.stdout)
        self.assertTrue((root / "data" / "alert_state.json").exists())
        # second run: nothing new should fire
        al2 = run("alert.py", root, "--dry")
        self.assertIn("No alert conditions", al2.stdout)


if __name__ == "__main__":
    unittest.main()
