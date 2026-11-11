#!/usr/bin/env python3
"""Send one ntfy push notification per run, based on docs/data/summary.json.

Alerts (thresholds in config.toml [alerts]):
  * price drop since the last check (RM or percent)
  * new lowest price seen
  * signal turned BOOK NOW or BOOK SOON
  * big jump up (a cheap fare tier probably sold out)
Use --dry to print instead of sending, --failure for the "monitor broke" message.
"""
import argparse
import os
import sys
import urllib.request

import common as c

STATE = c.DATA / "alert_state.json"


def dashboard_url():
    url = os.environ.get("DASHBOARD_URL", "").strip()
    if url:
        return url
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def decide(summary, state, cfg):
    a = cfg.get("alerts", {})
    lines, urgent, new_state = [], False, {}
    for it in summary["items"]:
        key = c.watch_key(it["label"], it["travel_date"])
        prev = state.get(key, {})
        latest = it["latest"]
        if not latest:
            new_state[key] = prev
            continue
        cur = latest["price"]
        parts = []

        # A manual re-run on the same day must not repeat that day's price alert.
        already_alerted_today = prev.get("date") == latest["date"]
        chg, prev_price = it["change_vs_prev"], it["previous_price"]
        if chg is not None and prev_price and not already_alerted_today:
            pct = abs(chg) / prev_price * 100
            if chg < 0 and (abs(chg) >= a.get("drop_rm", 20) or pct >= a.get("drop_pct", 8)):
                parts.append(f"down RM {abs(chg):.0f} (was {prev_price:.0f})")
                urgent = True
            elif chg > 0 and a.get("rise_rm", 0) and chg >= a["rise_rm"]:
                parts.append(f"jumped up RM {chg:.0f}; a cheap fare tier probably sold out")
        if (a.get("new_low", True) and it["checks"] >= 3 and prev.get("low") is not None
                and cur < prev["low"]):
            parts.append("new lowest price seen")
            urgent = True
        sig = it["signal"]
        if a.get("book_signal", True) and sig in ("BOOK NOW", "BOOK SOON") and prev.get("signal") != sig:
            parts.append(f"signal: {sig}. {it['reasons'][0] if it['reasons'] else ''}".strip())
            if sig == "BOOK NOW":
                urgent = True

        if parts:
            head = f"{it['label']} {it['travel_date']}: RM {cur:.0f} ({latest['airline']})"
            lines.append(head + "\n  " + "; ".join(parts))
        new_state[key] = {"signal": sig, "low": it["low"], "price": cur, "date": latest["date"]}

    if a.get("daily_summary", False):
        lines.append("Today: " + " | ".join(
            f"{it['label']} {it['travel_date'][5:]} RM {it['latest']['price']:.0f} {it['signal']}"
            for it in summary["items"] if it["latest"]))
    return lines, urgent, new_state


def send(title, body, priority, click):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("(NTFY_TOPIC not set: not sending)")
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title, "Priority": priority, "Tags": "airplane"}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(f"{server}/{topic}", data=body.encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print the alert instead of sending it")
    ap.add_argument("--failure", action="store_true", help="send the 'monitor failed' message")
    args = ap.parse_args()
    click = dashboard_url()

    if args.failure:
        body = "The daily flight price check failed. Open the GitHub Actions run to see why."
        print(body)
        if not args.dry:
            send("Flight monitor problem", body, "high", click)
        return 0

    cfg = c.load_config()
    summary = c.read_json(c.DOCS_DATA / "summary.json", None)
    if not summary:
        print("No summary.json yet; nothing to alert on.")
        return 0
    state = c.read_json(STATE, {})
    lines, urgent, new_state = decide(summary, state, cfg)
    c.write_json(STATE, new_state)

    if not lines:
        print("No alert conditions met today.")
        return 0
    body = "\n".join(lines)
    print(body)
    if not args.dry:
        send("Flight price alert", body, "high" if urgent else "default", click)
    return 0


if __name__ == "__main__":
    sys.exit(main())
