# KK flight price monitor

Records the cheapest nonstop Google Flights fare for Kota Kinabalu to Kuala Lumpur / Penang (and back) once a day,
keeps the full history, scores "wait or book", pushes alerts to your phone, and publishes a dashboard web page.
It runs on GitHub's servers, so your Mac can be off.

```
GitHub Actions (daily, 10:30 Malaysia time)
  scripts/fetch.py    -> asks SerpApi for Google Flights prices (1 search per route + date)
  scripts/analyze.py  -> history, price steps, wait/book signal  -> docs/data/summary.json
  scripts/alert.py    -> ntfy push notification to your phone
  commits data/prices.csv back to the repo, publishes docs/ as the dashboard
```

## One-time setup (about 20 minutes)

1. **GitHub account and repository.** Sign in at github.com, click **New repository**, name it `kk-flight-monitor`,
   choose **Public** (free GitHub Pages needs a public repo; your keys stay private in Secrets, see step 5).
2. **Upload this folder.** In Terminal on your Mac:
   ```
   cd path/to/kk-flight-monitor
   git init -b main
   git add .
   git commit -m "First version"
   git remote add origin https://github.com/YOUR-USERNAME/kk-flight-monitor.git
   git push -u origin main
   ```
   (GitHub Desktop works too: File > Add Local Repository, then Publish.)
3. **SerpApi key.** Sign up free at serpapi.com. The free plan gives 250 searches a month. Copy your API key.
4. **ntfy topic (your phone alerts).** Install the free **ntfy** app (iPhone or Android), tap **+**, and subscribe to a
   topic name that nobody can guess, for example `kkfly-` followed by 12 random letters and digits.
   Anyone who knows the topic can read it, so keep it private.
5. **Add secrets.** In the repo: **Settings > Secrets and variables > Actions > New repository secret**. Add two:
   - `SERPAPI_KEY` = your SerpApi key
   - `NTFY_TOPIC` = the topic name from step 4
6. **Turn on the dashboard.** **Settings > Pages > Build and deployment > Source: GitHub Actions**.
7. **Set your dates.** Open `config.toml`, change each `[[watch]]` date to the day you want to fly, commit the change.
8. **First run.** **Actions > Daily price check > Run workflow.** After about a minute your dashboard is at
   `https://YOUR-USERNAME.github.io/kk-flight-monitor/` and the first prices are in `data/prices.csv`.

From then on it runs by itself every morning.

## Option: free browser mode on your Mac (no SerpApi searches used)

`scripts/fetch_playwright.py` opens the real Google Flights page in a browser and records the fares into the
same `data/prices.csv`, so the dashboard, forecast and alerts work unchanged. It runs on your Mac (a home or
base connection), not on GitHub's servers, which Google often challenges.

1. Move the folder out of Downloads: `mv ~/Downloads/kk-flight-monitor ~/kk-flight-monitor`
2. `cd ~/kk-flight-monitor && bash mac/install.sh` (needs Python 3.11+; `brew install python` if missing).
3. First test, with the browser visible and debug files saved:
   `bash mac/run_monitor.sh --headed --debug --only "KK to KUL Tue"`
   If it records nothing, send the files in `data/debug/` (screenshot + HTML) so the page reader can be fixed.
4. It then runs by itself every day at 08:15 (or when the Mac wakes up after that), pushes the new data to
   GitHub, and the 10:30 GitHub job builds the dashboard. If the Mac was off, the 10:30 job fills the gap with
   SerpApi, so no day is lost. Logs: `~/Library/Logs/flightmonitor.log`.

It pauses 20-60 seconds between pages, runs one page at a time, and stops immediately if Google shows a
CAPTCHA. Automated access is against Google's terms; keep the volume this low and do not make it faster.

## What you get

- **Dashboard:** latest price, price history chart, lowest and highest seen, every airline's fare for the day,
  a signal (BOOK NOW / BOOK SOON / WAIT / WATCH) with the reasons, and how often prices step up or down.
- **Data:** `data/prices.csv` has one row per flight per day (check date, route, travel date, days to departure,
  airline, flight number, departure time, price). Open it in Excel or Numbers any time.
- **Alerts on your phone** when the cheapest fare drops by RM 20 or 8 percent, hits a new low, jumps up by RM 40
  (a cheap fare tier probably sold out), or the signal becomes BOOK NOW / BOOK SOON. Thresholds are in `config.toml`.
- **A "monitor broke" message** if a daily run fails.

## How the signal works (no black box)

The first rule that applies wins:

| Rule | Signal |
|---|---|
| 7 days or fewer to departure | BOOK NOW |
| Google rates the price "low" for the route | BOOK NOW |
| Lowest price seen since monitoring started (3+ checks) | BOOK NOW |
| 21 days or fewer to departure | BOOK SOON |
| 14+ daily checks and the price is in the cheapest fifth of its own history, or rising 0.5% a day or faster | BOOK SOON |
| 14+ daily checks, otherwise | WAIT |
| Google rates the price "high" | WAIT |
| Not enough history yet | WATCH |

This is a rule-based guide, not a trained forecast. With under about 4 weeks of data, treat it as a hint.
The "rough 7-day projection" on the dashboard is a straight-line estimate capped at plus or minus 20 percent.
The code is in `scripts/analyze.py` if you want to tune it once you have more data.

## Polite use and limits

- One search per route and date per day, one at a time, 5 seconds apart. Re-running on the same day does not search again.
- A monthly search budget (240) is enforced. 7 watch entries use about 217 searches a month; stay at 7 or fewer on the free plan.
- On HTTP 401, 403, 429 or "out of searches" it stops at once and does not retry.
- Google Flights has no official API. SerpApi reads Google Flights for you, and that is a grey area under Google's terms.
  Keep this for personal use and do not share the data commercially.
- Google Flights does not show seats left or fare class letters, so those columns from your manual sheet are not recorded here.
- A trip date that has passed is skipped automatically. The history stays in the CSV.
- GitHub pauses scheduled workflows in a repo with no activity for 60 days. The daily data commit counts as activity,
  but if alerts ever stop, open the Actions tab and re-enable the workflow.

## Checking it works

```
python3 -m unittest discover -s tests -v
```
runs 16 offline tests (parsing, signal rules, alert de-duplication, and a full fetch-analyse-alert run against a sample response).
`tests/simulate.py` can fill a throwaway copy with invented history to preview the dashboard; never run it in the real repo.

The parser was written from SerpApi's documented Google Flights response format and tested against a sample of that format,
not against live data. After your first real run, open `data/prices.csv` and check that the airlines, flight numbers and
prices look right.
