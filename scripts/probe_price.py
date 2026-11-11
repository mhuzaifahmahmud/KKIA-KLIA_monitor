#!/usr/bin/env python3
"""Find out why the automated browser sees different (higher) fares than a normal browser.

Opens ONE Google Flights search several times, each time with one thing changed (user-agent, language/time-zone
overrides, address format, visible window), and prints the cheapest fare each version sees. Compare the numbers
with the price you see by hand. Takes about 4 minutes; use it sparingly (a handful of pages, 20-40 s apart).

    .venv/bin/python scripts/probe_price.py --reference 379
"""
import argparse
import random
import sys
import time
from urllib.parse import quote

import fetch_playwright as fp

REAL_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/{v} Safari/537.36")


def simple_url(w):
    q = f"Flights to {w['to']} from {w['from']} on {w['date']} one way nonstop"
    return f"https://www.google.com/travel/flights?q={quote(q)}"


def run_variant(pw, name, w, settings, ctx_kwargs, mode, simple, args):
    launch_args = argparse.Namespace(headed=mode != 'headless', mode=mode, chrome_path=args.chrome_path)
    browser = fp.launch(pw, launch_args)
    try:
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, **ctx_kwargs)
        page = ctx.new_page()
        page.set_default_timeout(45000)
        if args.fixture:
            page.set_content(open(args.fixture, encoding="utf-8").read())
        else:
            url = simple if isinstance(simple, str) else (simple_url(w) if simple else fp.build_url(w, settings))
            page.goto(url, wait_until="domcontentloaded")
            fp.handle_consent(page)
            fp.check_blocked(page)
            fp.load_results(page)
        offers, _ = fp.scrape(page, settings)
        seen = page.evaluate("() => ({ua: navigator.userAgent, webdriver: navigator.webdriver, lang: navigator.language})")
        prices = sorted(o["price"] for o in offers)
        sample = ", ".join(f"{o['dep_time']} {o['airline'][:9]} {o['price']}" for o in offers[:4])
        print(f"{name}\n    cheapest: {prices[0] if prices else '-'}   flights: {len(offers)}   first rows: {sample}\n"
              f"    browser says: webdriver={seen['webdriver']} lang={seen['lang']}\n    ua={seen['ua'][:95]}")
        return prices[0] if prices else None
    finally:
        browser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="origin", default="KUL")
    ap.add_argument("--to", default="BKI")
    ap.add_argument("--date", default="2026-12-25")
    ap.add_argument("--reference", type=float, help="the cheapest price you see by hand right now")
    ap.add_argument("--url", help="the full address copied from your own Google Flights result page")
    ap.add_argument("--chrome-path")
    ap.add_argument("--fixture", help="offline test: HTML file instead of Google")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    w = {"from": args.origin, "to": args.to, "date": args.date}
    settings = {"currency": "MYR", "country": "my", "nonstop_only": True}
    my = dict(locale="en-MY", timezone_id="Asia/Kuala_Lumpur")

    with sync_playwright() as pw:
        probe = fp.launch(pw, argparse.Namespace(headed=False, chrome_path=args.chrome_path))
        version = probe.version
        probe.close()
        real_ua = REAL_UA.format(v=version)
        variants = [("C1  Chrome engine, our link (baseline)", dict(user_agent=fp.UA, **my), "headless", False),
                    ("S1  Safari engine (WebKit), our link", dict(**my), "webkit", False)]
        if args.url:
            clean = args.url.replace("&client=safari", "")
            variants += [
                ("S2  Safari engine (WebKit), YOUR link", dict(**my), "webkit", args.url),
                ("C2  Chrome engine, YOUR link without client=safari", dict(user_agent=fp.UA, **my), "headless", clean),
            ]
        results = []
        for i, (name, ctx_kwargs, mode, simple) in enumerate(variants):
            if i and not args.fixture:
                time.sleep(random.uniform(20, 40))
            try:
                results.append((name, run_variant(pw, name, w, settings, ctx_kwargs, mode, simple, args)))
            except fp.StopAll as e:
                print(f"STOP {e}")
                break
            except Exception as e:
                print(f"{name}\n    ERROR: {e}")
                results.append((name, None))

    print("\nSUMMARY  (route %s>%s on %s)" % (args.origin, args.to, args.date))
    if args.reference:
        print(f"  your manual search: {args.reference:.0f}")
    for name, price in results:
        flag = ""
        if price and args.reference:
            flag = "   <-- matches" if abs(price - args.reference) <= 3 else f"   ({price - args.reference:+.0f})"
        print(f"  {name}: {price if price else '-'}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
