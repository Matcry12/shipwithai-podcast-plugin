#!/usr/bin/env bash
# runner-doctor.sh -- is this machine able to run the podcast pipeline?
#
# Run it on a candidate automation box BEFORE registering a runner there. Every
# check maps to something that has actually broken a run; the fix line says what
# to do rather than just what failed.
#
#   bash scripts/runner-doctor.sh
#
# Exit 0 = ready. Exit 1 = at least one blocker.
set -uo pipefail

PODCAST="${PODCAST_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"

# Sourced here, before SITE below takes its ${VAR:-default} -- see the
# matching note in ci-podcast.sh. Otherwise this doctor would validate the
# hardcoded fallback paths instead of whatever .env actually configures.
set -a; . "$PODCAST/.env" 2>/dev/null; set +a

SITE="${SITE_REPO:-$HOME/Developer/shipwithai.io}"
fails=0
warns=0

# Every external call here gets a cap. 2026-09-24 the unbounded claude check
# below sat 87 minutes inside a CI job and printed nothing -- a doctor that can
# hang is worse than no doctor. macOS has no coreutils timeout; perl has alarm.
tmout() { perl -e 'alarm shift; exec @ARGV' "$@"; }

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n         fix: %s\n' "$1" "$2"; fails=$((fails+1)); }
warn() { printf '  \033[33mWARN\033[0m  %s\n         %s\n' "$1" "$2"; warns=$((warns+1)); }

echo "== binaries =="
b="$(command -v bash)"; v="$("$b" -c 'echo ${BASH_VERSINFO[0]}')"
[ "$v" -ge 4 ] && ok "bash $v ($b)" || bad "bash $v at $b -- ci-podcast.sh needs >= 4" "brew install bash, and put /opt/homebrew/bin before /bin on the runner's PATH"
for b in claude git python3 ffmpeg jq curl; do
  command -v "$b" >/dev/null && ok "$b" || bad "$b not on PATH" "install it, and make sure the runner's .env PATH includes it"
done
command -v browser-harness >/dev/null \
  && ok "browser-harness" \
  || bad "browser-harness not on PATH" "stage 3 drives a real browser; without it nothing can publish"

echo
echo "== claude =="
if tmout 60 claude -p "reply with the single word: ok" >/dev/null 2>&1; then
  ok "authenticated"
else
  bad "claude did not answer in 60s, or is not authenticated" "token: gh secret set CLAUDE_CODE_OAUTH_TOKEN. A hang with a valid token: see the npm-build note in runner/README.md"
fi

echo
echo "== repos =="
[ -d "$PODCAST/skills" ] && ok "podcast repo at $PODCAST" \
  || bad "podcast repo not found at $PODCAST" "clone it, then set PODCAST_REPO in ~/actions-runner/.env"
[ -d "$SITE/src/content/blog" ] && ok "site repo at $SITE" \
  || warn "site repo not at $SITE" "only needed for local runs; CI checks it out itself"

echo
echo "== render server =="
if [ -z "${PODCAST_URL:-}" ] || [ -z "${PODCAST_TOKEN:-}" ]; then
  bad "PODCAST_URL / PODCAST_TOKEN unset" "copy .env from a working machine (gitignored); see .env.example"
elif curl -fsS --max-time 10 -H "Authorization: Bearer $PODCAST_TOKEN" "$PODCAST_URL/health" >/dev/null 2>&1; then
  ok "reachable at $PODCAST_URL"
  case "$PODCAST_URL" in
    *localhost*|*127.0.0.1*) warn "PODCAST_URL is loopback" "only works if the render server is on THIS machine" ;;
    *192.168.*|*10.*)        warn "PODCAST_URL is a LAN address" "this box must stay on that network; a tailnet IP travels better" ;;
  esac
else
  bad "render server unreachable at ${PODCAST_URL:-<unset>}" "wake the render host, or point PODCAST_URL at an address this machine can reach"
fi

# Cloned voices are the main EN path; without these the skill silently falls
# back to kokoro presets and the episodes stop sounding like your show.
echo
echo "== voices (omnivoice, the EN main path) =="
for v in PODCAST_EN_VOICE PODCAST_EN_VOICE_2; do
  p="$(eval echo "\${$v:-}")"
  if [ -z "$p" ]; then warn "$v unset" "EN will fall back to kokoro presets instead of your cloned voices"
  elif [ -f "$p" ]; then ok "$v -> $(basename "$p")"
  else bad "$v points at a missing file: $p" "copy the .wav clips across and fix the path"; fi
done

echo
echo "== display (stage 3 needs a real browser) =="
if [ "$(uname)" = Darwin ]; then
  # No X here; browser-harness reaches Chrome over CDP. A dedicated Chrome
  # launched with --remote-debugging-port never shows the "Allow remote
  # debugging?" popup that stalled unattended runs on the Linux box.
  cdp="${BU_CDP_URL:-http://127.0.0.1:9333}"
  curl -fsS --max-time 3 "$cdp/json/version" >/dev/null 2>&1 \
    && ok "Chrome answering CDP at $cdp" \
    || bad "no Chrome on $cdp" "open -a 'Google Chrome' --args --remote-debugging-port=9333 --user-data-dir=\$HOME/podcast/chrome-profile, log into Spotify in it once, set BU_CDP_URL in ~/actions-runner/.env"
  # The cookies are the whole publishing credential and they expire on their
  # own schedule. Without this the first sign of trouble is a failed publish
  # in a real run, halfway through an episode nobody can finish.
  if command -v browser-harness >/dev/null && curl -fsS --max-time 3 "$cdp/json/version" >/dev/null 2>&1; then
    u="$(BU_CDP_URL="$cdp" BU_NAME="${BU_NAME:-podcast}" tmout 120 browser-harness <<'BH' 2>/dev/null
import time
new_tab("https://creators.spotify.com/home"); wait_for_load()
# The dashboard lands on the bare host and then routes client-side, so the
# first URL read says nothing. Logged out, it bounces to the login host.
for _ in range(10):
    u = page_info()["url"]
    if "accounts.spotify.com" in u or "/login" in u or "/home" in u:
        break
    time.sleep(1)
print(u)
BH
)"
    case "$u" in
      *accounts.spotify.com*|*/login*)
            bad "spotify session expired (bounced to ${u:0:50})" "re-login remotely: the cookie hand-over in runner/README.md" ;;
      *creators.spotify.com*) ok "spotify session live" ;;
      "")   warn "spotify check did not return" "browser-harness timed out against $cdp -- re-run, then restart the Chrome LaunchAgent" ;;
      *)    warn "spotify check landed somewhere unexpected: ${u:0:60}" "look at the dashboard by hand before trusting the next publish" ;;
    esac
  fi
elif [ -n "${DISPLAY:-}" ]; then
  ok "DISPLAY=$DISPLAY"
  [ -n "${XAUTHORITY:-}" ] && [ -f "${XAUTHORITY:-}" ] && ok "XAUTHORITY readable" \
    || warn "XAUTHORITY unset or missing" "a systemd service has no session; set it in ~/actions-runner/.env"
else
  bad "no DISPLAY" "headless box needs Xvfb, plus a one-time interactive Spotify login in that browser profile"
fi

echo
echo "== runner =="
RUNNER="${RUNNER_DIR:-$HOME/actions-runner}"
if [ -f "$RUNNER/.runner" ]; then
  ok "registered"
  { systemctl --user list-units --all 2>/dev/null; launchctl list 2>/dev/null; :; } | grep actions.runner >/dev/null \
    && ok "installed as a service" \
    || warn "not a service" "it dies with your shell and jobs then queue with no error: see runner/README.md"
else
  warn "no runner registered here" "Settings -> Actions -> Runners -> New self-hosted runner, then ./config.sh --labels podcast"
fi

echo
if [ "$fails" -gt 0 ]; then
  echo "NOT READY -- $fails blocker(s), $warns warning(s)"
  exit 1
fi
echo "READY -- $warns warning(s)"
