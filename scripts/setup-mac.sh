#!/usr/bin/env bash
# setup-mac.sh -- bootstrap a Mac mini as the podcast runner, under ~/podcast/.
#
#   curl -fsSLO https://raw.githubusercontent.com/Matcry12/shipwithai-podcast-plugin/master/scripts/setup-mac.sh
#   bash setup-mac.sh
#
# Download first, then run -- NOT `curl | bash`: the GitHub login inside needs
# the keyboard. Safe to rerun: every step skips what already exists. It does
# everything a script CAN do; the three things it cannot (logins tied to a
# human's accounts, and the runner token) it stops for or prints at the end.
#
#   ~/podcast/plugin            this repo
#   ~/podcast/browser-harness   browser tool
#   ~/podcast/voices            copied by hand from the writing machine
#   ~/podcast/runner            GitHub runner (registered by hand: needs token)
#   ~/podcast/chrome-profile    the Spotify-logged-in Chrome
set -euo pipefail
P="$HOME/podcast"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Linux is supported only so the script can be tested for real on the writing
# machine: no installs there (the runner-doctor names what is missing), GNU sed,
# and no pmset.
MAC=false; [ "$(uname)" = Darwin ] && MAC=true
install() { if $MAC; then brew install "$@"; else echo "  MISSING $*: install it, then rerun"; exit 1; fi; }
sedi()    { if $MAC; then sed -i '' "$@"; else sed -i "$@"; fi; }

step "tools"
$MAC && ! have brew && { echo "Homebrew missing -- install from https://brew.sh then rerun"; exit 1; }
for b in ffmpeg jq gh uv node python3; do have "$b" && echo "  ok $b" || install "$b"; done
# ci-podcast.sh needs bash >= 4 (mapfile); macOS /bin/bash is 3.2. Homebrew's
# bash wins because /opt/homebrew/bin precedes /bin on the runner's PATH.
if $MAC; then [ -x /opt/homebrew/bin/bash ] && echo "  ok bash 5" || brew install bash; fi
have claude && echo "  ok claude" || npm i -g @anthropic-ai/claude-code
if $MAC; then [ -d "/Applications/Google Chrome.app" ] && echo "  ok chrome" || brew install --cask google-chrome; fi

# The plugin repo is private, so cloning needs a GitHub login. gh handles the
# credential and the clone; no SSH key to set up on this box.
step "github login"
gh auth status >/dev/null 2>&1 && echo "  ok gh" || gh auth login --hostname github.com --git-protocol https --web

step "code under $P"
mkdir -p "$P"
[ -d "$P/plugin/.git" ] && echo "  ok plugin" \
  || gh repo clone Matcry12/shipwithai-podcast-plugin "$P/plugin"
[ -d "$P/browser-harness/.git" ] && echo "  ok browser-harness" \
  || git clone https://github.com/browser-use/browser-harness "$P/browser-harness"
have browser-harness && echo "  ok browser-harness on PATH" \
  || (cd "$P/browser-harness" && uv tool install -e . && uv tool update-shell)

step "claude knows the browser tool"
mkdir -p "$HOME/.claude"
grep -qs "browser-harness/SKILL.md" "$HOME/.claude/CLAUDE.md" && echo "  ok" \
  || printf '# browser-harness\n@~/podcast/browser-harness/SKILL.md\n' >> "$HOME/.claude/CLAUDE.md"

step "runner settings"
mkdir -p "$P/runner"
[ -f "$P/runner/.env" ] && echo "  ok $P/runner/.env" || cat > "$P/runner/.env" <<EOF
PATH=$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
PODCAST_REPO=$P/plugin
BU_NAME=podcast
BU_CDP_URL=http://127.0.0.1:9333
HOME=$HOME
LANG=en_US.UTF-8
EOF

if $MAC; then
  # The publish stage drives THIS Chrome: launched with the debugging port (so
  # no "Allow remote debugging?" popup, ever) on its own profile (so it never
  # touches a Chrome someone is using). KeepAlive brings it back after a crash
  # or reboot. Log into Spotify for Creators in it once; the profile persists.
  step "dedicated chrome (launchd, port 9333)"
  PL="$HOME/Library/LaunchAgents/podcast.chrome.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  if [ -f "$PL" ]; then echo "  ok $PL"; else
    cat > "$PL" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>podcast.chrome</string>
  <key>ProgramArguments</key><array>
    <string>/Applications/Google Chrome.app/Contents/MacOS/Google Chrome</string>
    <string>--remote-debugging-port=9333</string>
    <string>--remote-allow-origins=*</string>
    <string>--user-data-dir=$P/chrome-profile</string>
    <string>--no-first-run</string>
    <string>--window-size=1400,900</string>
    <string>https://creators.spotify.com/home/show/</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
EOF
    launchctl load "$PL" && echo "  started"
  fi

  step "never sleep (asks for your password)"
  sudo pmset -a sleep 0 disksleep 0 displaysleep 10 && echo "  ok pmset"
fi

# .env voice paths still say /home/matcry after a copy; fix them if the file is here.
if [ -f "$P/plugin/.env" ]; then
  sedi "s#/home/matcry/voice_lab/voices#$P/voices#g" "$P/plugin/.env"
  echo "  ok .env voice paths -> $P/voices"
fi

cat <<EOF

DONE with the automatic part. Three things need YOU:

  1. copy from the writing machine (any way you like):
       voices/*.wav -> $P/voices/      .env -> $P/plugin/.env
     then run this script once more so it fixes the voice paths inside .env
  2. claude           (type /login, finish in the browser, then /exit)
  3. a Chrome window titled with the Spotify login just opened (the dedicated one,
     port 9333) -> log into Spotify for Creators in it, once. Leave it open; it
     comes back by itself after a reboot.

Then check:
  cd $P/plugin && RUNNER_DIR=$P/runner BU_CDP_URL=http://127.0.0.1:9333 bash scripts/runner-doctor.sh

Then register the runner (fresh token from the repo admin: New self-hosted runner -> macOS -> ARM64):
  cd $P/runner && <paste GitHub's curl + tar lines> && ./config.sh --url ... --token ... --labels podcast
  ./svc.sh install && ./svc.sh start
And: System Settings -> Users & Groups -> Automatic login -> this user.
EOF
