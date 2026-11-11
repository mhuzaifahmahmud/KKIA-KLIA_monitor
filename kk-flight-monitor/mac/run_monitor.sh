#!/bin/bash
# Daily job for your Mac: pull latest config, record prices from Google Flights in a browser,
# then push the new data to GitHub. Started by launchd (see mac/install.sh), or run it by hand.
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="

# Wait up to 2 minutes for the network (the Mac may have just woken up).
for i in $(seq 1 24); do
  curl -fsS -o /dev/null --max-time 5 https://github.com && break
  sleep 5
done

git pull --rebase --autostash -q || echo "WARN: git pull failed; continuing with local copy"

"$DIR/.venv/bin/python" scripts/fetch_playwright.py "$@"
status=$?

git add data
if git diff --cached --quiet; then
  echo "no new data to push"
else
  git commit -q -m "Browser price check $(date '+%Y-%m-%d %H:%M')"
  git push -q || { git pull --rebase -q && git push -q; } || echo "WARN: push failed"
fi
echo "finished with status $status"
exit $status
