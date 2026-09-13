#!/usr/bin/env bash
# setup-mac.sh -- bootstrap a Mac mini as the podcast runner, under ~/podcast/.
#
#   curl -fsSL https://raw.githubusercontent.com/Matcry12/shipwithai-podcast-plugin/master/scripts/setup-mac.sh | bash
#
# Safe to rerun: every step skips what already exists. It does everything that
# a script CAN do; the four things it cannot (three logins and the runner
# token, all tied to a human's accounts) are printed at the end.
#
#   ~/podcast/plugin            this repo
#   ~/podcast/browser-harness   browser tool
#   ~/podcast/drafts            copied by hand from the writing machine
#   ~/podcast/voices            copied by hand from the writing machine
#   ~/podcast/runner            GitHub runner (registered by hand: needs token)
#   ~/podcast/chrome-profile    the Spotify-logged-in Chrome
set -euo pipefail
P="$HOME/podcast"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

[ "$(uname)" = Darwin ] || { echo "this is the macOS bootstrap; on Linux see runner/README.md"; exit 1; }

step "tools"
have brew || { echo "Homebrew missing -- install from https://brew.sh then rerun"; exit 1; }
for b in ffmpeg jq gh uv node; do have "$b" && echo "  ok $b" || brew install "$b"; done
have claude && echo "  ok claude" || npm i -g @anthropic-ai/claude-code

step "code under $P"
mkdir -p "$P"
[ -d "$P/plugin/.git" ] && echo "  ok plugin" \
  || git clone git@github.com:Matcry12/shipwithai-podcast-plugin.git "$P/plugin"
[ -d "$P/browser-harness/.git" ] && echo "  ok browser-harness" \
  || git clone git@github.com:browser-use/browser-harness.git "$P/browser-harness"
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
DRAFTS_DIR=$P/drafts
BU_CDP_URL=http://127.0.0.1:9222
HOME=$HOME
LANG=en_US.UTF-8
EOF

step "never sleep"
sudo pmset -a sleep 0 disksleep 0 displaysleep 10 && echo "  ok pmset"

# .env voice paths still say /home/matcry after a copy; fix them if the file is here.
[ -f "$P/plugin/.env" ] && sed -i '' "s#/home/matcry/voice_lab/voices#$P/voices#g" "$P/plugin/.env"

cat <<EOF

DONE with the automatic part. Four things need YOU (they are logins):

  1. copy from the writing machine:
       drafts/  -> $P/drafts/      voices/*.wav -> $P/voices/      .env -> $P/plugin/.env
     then rerun this script once so it fixes the voice paths in .env
  2. claude           (then type /login, finish in the browser, /exit)
  3. gh auth login    (GitHub.com -> SSH -> browser)
  4. open -a "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=$P/chrome-profile
     -> log into creators.spotify.com/home in that window, leave it open

Then check:   cd $P/plugin && DRAFTS_DIR=$P/drafts RUNNER_DIR=$P/runner BU_CDP_URL=http://127.0.0.1:9222 bash scripts/runner-doctor.sh
Then register the runner (needs a fresh token from the repo admin, macOS/ARM64):
     cd $P/runner && <GitHub's curl + tar lines> && ./config.sh --url ... --token ... --labels podcast
     ./svc.sh install && ./svc.sh start
And enable: System Settings -> Users & Groups -> Automatic login.
EOF
