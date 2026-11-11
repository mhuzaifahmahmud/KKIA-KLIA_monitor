#!/usr/bin/env python3
"""Record today's Google Flights prices by opening the real Google Flights page in a browser.

This is the "free, no API key" alternative to fetch.py (SerpApi). It writes to the same
data/prices.csv and data/insights.csv, so analyze.py, alert.py and the dashboard work unchanged.
Meant to run on your own computer (a home or base connection), not on GitHub's servers.

Polite by design:
  * one page per route+date per day, never repeated the same day (use --force to override)
  * one browser, one page at a time, a random 20-60 second pause between pages
  * stops at once on a CAPTCHA, "unusual traffic" page or a block; never tries to get around it
  * three failures in a row also stop the run

First run on a new machine: use  --debug --headed  to watch it work and to save a screenshot
plus the page HTML of every search into data/debug/ (never committed).
"""
import argparse
import os
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from urllib.parse import quote

import common as c

SOURCE = "Google Flights (browser)"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

PRICE_RE = re.compile(r"(?:RM|MYR)\s?(\d{1,3}(?:,\d{3})+|\d+)")
PRICE_LABEL_RE = re.compile(r"(?:from\s+)?(\d{1,3}(?:,\d{3})+|\d+)\s+malaysian ringgit", re.I)
TIME12_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s?([AaPp])\.?[Mm]\.?")
TIME24_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
LEAVES_RE = re.compile(r"leaves .{0,80}? at (\d{1,2}:\d{2}\s?[AaPp]\.?[Mm]\.?|\d{1,2}:\d{2})", re.I)
AIRLINE_LABEL_RE = re.compile(r"(?:nonstop|\d+ stops?) flight with ([^.]+?)\.", re.I)
STOPS_RE = re.compile(r"\b(\d+)\s+stops?\b", re.I)

# What the list shows on every result row, so it can never be the airline name.
NOT_AIRLINE = re.compile(
    r"(\d{1,2}:\d{2})|\bhr\b|\bmin\b|\bkg\b|co2|emission|nonstop|\bstops?\b|^(rm|myr)\b|"
    r"^[A-Z]{3}\s*[–-]\s*[A-Z]{3}$|^\d|round trip|one way|price|ringgit|carry-on|bag|"
    r"operated by|self.transfer|overnight|\+\d", re.I)

JS_EXTRACT = """() => {
  const cards = [], seen = new Set();
  for (const li of document.querySelectorAll('li')) {
    if (li.querySelector('li')) continue;                 // innermost rows only
    const t = li.innerText || '';
    if (!/(RM|MYR)\\s?\\d/.test(t) || !/\\d{1,2}:\\d{2}/.test(t)) continue;
    if (seen.has(t)) continue;
    seen.add(t);
    const labels = [...li.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label'));
    cards.push({text: t, labels});
  }
  return {cards, body: document.body ? document.body.innerText : ''};
}"""


class StopAll(Exception):
    """Continuing would be impolite or pointless (CAPTCHA, block, repeated failures)."""


def norm(text):
    text = (text or "").replace(" ", " ").replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"[ \t]+", " ", text)


def to_24h(hour, minute, ampm=None):
    h = int(hour) % 12 if ampm else int(hour)
    if ampm and ampm.lower() == "p":
        h += 12
    return f"{h:02d}:{int(minute):02d}"


def parse_time(text):
    m = TIME12_RE.search(text)
    if m:
        return to_24h(m.group(1), m.group(2), m.group(3))
    m = TIME24_RE.search(text)
    return to_24h(m.group(1), m.group(2)) if m else ""


def parse_cards(cards, default_stops=0):
    """Turn the rows scraped from the page into the same offer dicts fetch.parse_offers returns."""
    offers, seen = [], set()
    for card in cards:
        text = norm(card.get("text", ""))
        labels = [norm(x) for x in card.get("labels", []) if x]
        blob = text + "\n" + "\n".join(labels)

        price = None
        for lab in labels:
            m = PRICE_LABEL_RE.search(lab)
            if m:
                price = int(m.group(1).replace(",", ""))
                break
        if price is None:
            m = PRICE_RE.search(text)
            if m:
                price = int(m.group(1).replace(",", ""))
        if price is None:
            continue

        if re.search(r"nonstop", blob, re.I):
            stops = 0
        else:
            m = STOPS_RE.search(blob)
            stops = int(m.group(1)) if m else default_stops

        dep = ""
        for lab in labels:
            m = LEAVES_RE.search(lab)
            if m:
                dep = parse_time(m.group(1))
                break
        dep = dep or parse_time(text)

        airline = ""
        for lab in labels:
            m = AIRLINE_LABEL_RE.search(lab)
            if m:
                airline = m.group(1).strip()
                break
        if not airline:
            for line in (ln.strip() for ln in text.splitlines()):
                if line and re.search(r"[A-Za-z]{3}", line) and not NOT_AIRLINE.search(line):
                    airline = line
                    break
        airline = airline or "Unknown"

        key = (airline, dep, price, stops)
        if key in seen:
            continue
        seen.add(key)
        offers.append({"airline": airline, "flight_no": "", "dep_time": dep,
                       "stops": stops, "price": price})
    return offers


def parse_insights(body, offers):
    """Best effort: Google's banner ('Prices are currently low/typical/high') if it is on the page."""
    body = norm(body)
    level = ""
    m = re.search(r"prices? (?:are|is) (?:currently )?(low|typical|high)", body, re.I)
    if m:
        level = m.group(1).lower()
    lo = hi = None
    m = re.search(r"typical[^.\n]{0,60}?(?:RM|MYR)\s?(\d[\d,]*)\s*(?:–|-|to|and)\s*(?:RM|MYR)?\s?(\d[\d,]*)",
                  body, re.I)
    if m:
        lo, hi = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
    return {"price_level": level, "lowest_price": min((o["price"] for o in offers), default=None),
            "typical_low": lo, "typical_high": hi}


def build_url(watch, settings):
    q = f"Flights to {watch['to']} from {watch['from']} on {watch['date']} one way"
    if settings.get("nonstop_only", True):
        q += " nonstop"
    return (f"https://www.google.com/travel/flights?q={quote(q)}"
            f"&curr={settings.get('currency', 'MYR')}&hl=en&gl={settings.get('country', 'my')}")


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def save_debug(page, label, travel, why):
    folder = c.DATA / "debug"
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{slug(label)}_{travel}_{why}"
    try:
        page.screenshot(path=str(base) + ".png", full_page=True)
        (folder / (base.name + ".html")).write_text(page.content(), encoding="utf-8")
        print(f"       debug files saved: data/debug/{base.name}.png / .html")
    except Exception as e:  # debugging must never crash the run
        print(f"       could not save debug files: {e}")


def check_blocked(page):
    url = page.url.lower()
    body = ""
    try:
        body = page.inner_text("body", timeout=3000).lower()
    except Exception:
        pass
    if "/sorry/" in url or "unusual traffic" in body or "captcha" in body or "not a robot" in body:
        raise StopAll("Google is asking for a CAPTCHA / reports unusual traffic; stopping without retrying")


def handle_consent(page):
    """Click through Google's cookie consent page if it appears (EU-style redirect)."""
    if "consent." not in page.url:
        return
    for name in (r"Reject all", r"Accept all", r"I agree", r"Tolak semua", r"Terima semua"):
        btn = page.get_by_role("button", name=re.compile(name, re.I))
        if btn.count():
            btn.first.click()
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            return


def load_results(page, debug_wait=30000):
    """Wait until fares show up; expand the list once. Returns False if the page says no flights."""
    try:
        page.wait_for_function(r"() => /(RM|MYR)\s?\d/.test(document.body.innerText)", timeout=debug_wait)
    except Exception:
        body = norm(page.inner_text("body")).lower()
        if "no options" in body or "no flights" in body or "no results" in body:
            return False
        raise
    page.wait_for_timeout(2500)  # let the rest of the list render
    more = page.get_by_role("button", name=re.compile(r"more flights", re.I))
    try:
        if more.count():
            more.first.click()
            page.wait_for_timeout(2000)
    except Exception:
        pass
    return True


def scrape(page, settings):
    data = page.evaluate(JS_EXTRACT)
    offers = parse_cards(data["cards"], default_stops=0 if settings.get("nonstop_only", True) else 1)
    return offers, parse_insights(data["body"], offers)


def launch(pw, args):
    opts = {"headless": not args.headed}
    path = args.chrome_path or os.environ.get("CHROME_PATH")
    if path:
        return pw.chromium.launch(executable_path=path, **opts)
    try:
        return pw.chromium.launch(**opts)
    except Exception:
        return pw.chromium.launch(channel="chrome", **opts)  # falls back to an installed Google Chrome


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to config.toml (default: project root)")
    ap.add_argument("--force", action="store_true", help="search again even if today's data exists")
    ap.add_argument("--only", help="only run watches whose label contains this text")
    ap.add_argument("--headed", action="store_true", help="show the browser window (first-run checking)")
    ap.add_argument("--debug", action="store_true", help="save a screenshot + HTML of every page to data/debug/")
    ap.add_argument("--chrome-path", help="path to a Chrome/Chromium executable (or set CHROME_PATH)")
    ap.add_argument("--fixture", help="HTML file to parse instead of opening Google (offline test)")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright is not installed. Run:  pip install playwright && playwright install chromium")
        return 2

    cfg = c.load_config(args.config)
    s = cfg.get("settings", {})
    now = c.local_now(cfg)
    today = now.date()
    dmin = float(s.get("browser_delay_min", 20))
    dmax = float(s.get("browser_delay_max", 60))

    existing = c.read_csv(c.DATA / "prices.csv")
    done = {(r["check_date"], r["route"], r["travel_date"]) for r in existing}

    todo, skipped = [], 0
    for w in cfg.get("watch", []):
        label, travel = w["label"], w["date"]
        if args.only and args.only.lower() not in label.lower():
            continue
        if date.fromisoformat(travel) < today:
            print(f"skip   {label} {travel}: travel date has passed")
            skipped += 1
        elif (today.isoformat(), label, travel) in done and not args.force:
            print(f"skip   {label} {travel}: already recorded today")
            skipped += 1
        else:
            todo.append(w)
    if not todo:
        print(f"done: nothing to do ({skipped} skipped)")
        return 0

    ok = failed = streak = 0
    with sync_playwright() as pw:
        browser = launch(pw, args)
        ctx = browser.new_context(user_agent=UA, locale="en-MY", timezone_id="Asia/Kuala_Lumpur",
                                  viewport={"width": 1366, "height": 900},
                                  extra_http_headers={"Accept-Language": "en-MY,en;q=0.9"})
        page = ctx.new_page()
        page.set_default_timeout(45000)
        try:
            for i, w in enumerate(todo):
                label, travel = w["label"], w["date"]
                if i and not args.fixture:
                    pause = random.uniform(dmin, dmax)
                    print(f"       waiting {pause:.0f}s before the next page")
                    time.sleep(pause)
                try:
                    if args.fixture:
                        page.set_content(open(args.fixture, encoding="utf-8").read())
                        found = True
                    else:
                        page.goto(build_url(w, s), wait_until="domcontentloaded")
                        handle_consent(page)
                        check_blocked(page)
                        found = load_results(page)
                    check_blocked(page)
                    offers, ins = scrape(page, s) if found else ([], None)
                    if args.debug:
                        save_debug(page, label, travel, "ok" if offers else "empty")
                    if not offers:
                        raise RuntimeError("no fares found on the page (layout changed, no flights that day, or blocked)")
                except StopAll as e:
                    save_debug(page, label, travel, "blocked")
                    print(f"STOP   {e}")
                    failed += 1
                    break
                except Exception as e:
                    print(f"ERROR  {label} {travel}: {e}")
                    save_debug(page, label, travel, "error")
                    failed += 1
                    streak += 1
                    if streak >= 3:
                        print("STOP   three failures in a row; stopping")
                        break
                    continue
                streak = 0

                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                days_left = (date.fromisoformat(travel) - today).days
                c.append_csv(c.DATA / "prices.csv", c.PRICE_FIELDS, [{
                    "check_date": today.isoformat(), "check_time_utc": stamp, "route": label,
                    "origin": w["from"], "destination": w["to"], "travel_date": travel,
                    "days_to_departure": days_left, "airline": o["airline"], "flight_no": o["flight_no"],
                    "dep_time": o["dep_time"], "stops": o["stops"], "price": o["price"],
                    "currency": s.get("currency", "MYR"), "source": SOURCE,
                } for o in offers])
                c.append_csv(c.DATA / "insights.csv", c.INSIGHT_FIELDS, [{
                    "check_date": today.isoformat(), "route": label, "travel_date": travel,
                    "price_level": ins["price_level"], "lowest_price": ins["lowest_price"],
                    "typical_low": ins["typical_low"], "typical_high": ins["typical_high"]}])
                print(f"ok     {label} {travel}: {len(offers)} flights, cheapest {ins['lowest_price']}")
                ok += 1
        finally:
            browser.close()

    print(f"done: {ok} recorded, {skipped} skipped, {failed} failed")
    return 1 if (failed and not ok) else 0


if __name__ == "__main__":
    sys.exit(main())
