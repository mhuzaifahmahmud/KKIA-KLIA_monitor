#!/bin/bash
# One-time setup on your Mac:  bash mac/install.sh
# Creates a private Python environment, installs Playwright + Chromium, and schedules the daily run.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
case "$DIR" in
  "$HOME/Downloads"*|"$HOME/Documents"*|"$HOME/Desktop"*)
    echo "Please move this folder to your home folder first, e.g.:"
    echo "  mv \"$DIR\" ~/kk-flight-monitor && cd ~/kk-flight-monitor && bash mac/install.sh"
    echo "(macOS blocks scheduled jobs from reading Downloads/Documents/Desktop.)"
    exit 1;;
esac

PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is needed. Install it with:  brew install python   (then run this again)"
  exit 1
fi

"$PY" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip playwright
.venv/bin/playwright install chromium
chmod +x mac/run_monitor.sh

PLIST="$HOME/Library/LaunchAgents/com.huzaifah.flightmonitor.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s#__DIR__#$DIR#g" -e "s#__HOME__#$HOME#g" mac/com.huzaifah.flightmonitor.plist > "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "Installed. It will run every day at 08:15 (or when the Mac wakes up after that)."
echo "Logs: ~/Library/Logs/flightmonitor.log"
echo "Test it now (watch the browser):  bash mac/run_monitor.sh --headed --debug --only 'KK to KUL Tue'"
