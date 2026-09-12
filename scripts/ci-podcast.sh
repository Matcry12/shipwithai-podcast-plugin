#!/usr/bin/env bash
# ci-podcast.sh -- one push worth of podcast work. Called by the site repo's
# .github/workflows/podcast.yml on a self-hosted runner.
#
# This is scripts/demo-podcast-listener.sh with the watch loop removed:
# GitHub Actions supplies the trigger, and $BEFORE/$AFTER supply the two shas
# the loop used to diff by hand.
#
# NOT /content-podcast-all: that command hard-codes the posting stage's human
# confirm gate and does not forward --yes-publish, so under CI it would block on
# a prompt until the job times out. The three stages are called separately for
# exactly that flag.
#
# !! Stage 3 passes --yes-publish. Every qualifying push publishes irreversibly
# !! to a PUBLIC Spotify feed with no human check.
set -uo pipefail

SITE="${SITE_REPO:?SITE_REPO not set}"
# This repo. Everything the pipeline produces (podcasts/, podcast-reports/)
# lives here.
PODCAST="${PODCAST_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"

# Drafts are written by the CONTENT plugin, not this one, and are gitignored
# there -- so they arrive by neither git nor this repo. Point DRAFTS_DIR at
# whatever directory holds them on this machine.
DRAFTS="${DRAFTS_DIR:-$HOME/Developer/shipwithai-content-agent-plugin/drafts}"
BRANCH="${BRANCH:?BRANCH not set}"
BEFORE="${BEFORE:?}"; AFTER="${AFTER:?}"
PERM_MODE="${DEMO_PERM_MODE:-bypassPermissions}"
MAX="${PODCAST_MAX_PER_PUSH:-3}"

# Empty means let the skill auto-detect, which is omnivoice for EN whenever the
# voice clips are configured -- the cloned-voice main path. kokoro is the skill's
# FALLBACK for when they are not, so forcing it here would silently ship preset
# voices instead of yours.
#
# Known hazard: omnivoice cloning can exhaust the render host's MPS memory. One
# 20-turn script took 34 min of chunked retries and still dropped a single turn
# to kokoro, leaving one line in a different voice. That is a render-host memory
# problem to fix there, not a reason to change engine. PODCAST_ENGINE=kokoro is
# the escape hatch if that host is unavailable and an episode has to ship.
ENGINE="${PODCAST_ENGINE:-}"

# Render->review cycles before giving up and asking for a human. Three, not
# two: a `regenerate` followed by a `fix` is progress, and the `fix` has not yet
# had its own repair attempt. Observed 2026-09-12 on the first VI run -- the
# script was clean at 34/35 and only the audio tail needed re-rendering, but the
# loop had already spent both cycles.
CYCLES="${PODCAST_MAX_CYCLES:-3}"

set -a; . "$PODCAST/.env" 2>/dev/null; set +a

# claude -p ends the session the moment the agent returns, so anything it pushed
# to the background is simply lost. Observed twice: the render stage submitted
# the job, said it would collect the mp3 "once it comes back", and exited with
# status 0 having produced only the dialogue script. Every prompt carries this.
CI_NOTE='

CONTEXT: this is a non-interactive CI session that terminates the instant you
return. Run every long step in the FOREGROUND and block until it finishes. Do
not background a command, do not defer work to a later check-in or wakeup, and
do not return until the artifacts exist on disk. A backgrounded task is lost.'

run() { ( cd "$PODCAST" && claude -p --permission-mode "$PERM_MODE" "$1$CI_NOTE" ); }

# Render writes type:"" ; posting fills it. A zero exit from the posting stage
# does not prove the publish landed -- the stub does.
stub_type() {
  python3 - "$1" <<'PY' 2>/dev/null
import json,sys
try: print(json.load(open(sys.argv[1]))["podcast"]["type"] or "", end="")
except Exception: pass
PY
}

# What arrived first, preflight second. Most pushes carry no blog post at all,
# and those should not fail merely because the render host is asleep -- it is
# also what lets the runner wiring be tested before that host exists.
#
# A brand-new branch reports before as all-zeros; there is nothing to diff
# against, so take the files introduced by the head commit alone.
ZERO=0000000000000000000000000000000000000000
if [ "$BEFORE" = "$ZERO" ]; then
  mapfile -t arrived < <(git -C "$SITE" show --name-only --pretty=format: "$AFTER" \
    -- 'src/content/blog/en/*.md' 'src/content/blog/vi/*.md' | grep -v '^$')
else
  mapfile -t arrived < <(git -C "$SITE" diff --name-only "$BEFORE" "$AFTER" \
    -- 'src/content/blog/en/*.md' 'src/content/blog/vi/*.md')
fi

[ "${#arrived[@]}" -eq 0 ] && { echo "no blog posts in this push"; exit 0; }

# Drop the already-done posts BEFORE preflight. Editing a post that already has
# an episode is the common case, and it needs no render server -- demanding one
# would fail the job over work that was never going to happen.
todo=()
for post in "${arrived[@]}"; do
  if grep -q '^podcast:' "$SITE/$post"; then
    echo "SKIP: $(basename "$post" .md) already has a podcast block"
  else
    todo+=("$post")
  fi
done
[ "${#todo[@]}" -eq 0 ] && { echo "nothing to podcast in this push"; exit 0; }

if [ "${#todo[@]}" -gt "$MAX" ]; then
  echo "capped at $MAX of ${#todo[@]} (raise PODCAST_MAX_PER_PUSH)"
  todo=("${todo[@]:0:$MAX}")
fi

echo "::group::preflight"
# Remote render server (the tuned TTS engines), not local Kokoro. PODCAST_URL
# points at a LAN address, so this runner must be on the same network as the
# render host AND that host must be awake. When a run fails here, that is almost
# always why. Moving the runner off this LAN means giving the render host a
# routable address (its tailnet IP would work).
[ -n "${PODCAST_URL:-}" ] && [ -n "${PODCAST_TOKEN:-}" ] \
  || { echo "PODCAST_URL / PODCAST_TOKEN not set -- check $PODCAST/.env"; exit 1; }
curl -fsS --max-time 10 -H "Authorization: Bearer $PODCAST_TOKEN" "$PODCAST_URL/health" >/dev/null \
  || { echo "render server unreachable at $PODCAST_URL -- is the render host awake?"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg MISSING"; exit 1; }
command -v browser-harness >/dev/null || { echo "browser-harness not on PATH"; exit 1; }
claude -p "reply with the single word: ok" >/dev/null 2>&1 \
  || { echo "claude not authenticated on this runner"; exit 1; }
echo "ok"
echo "::endgroup::"

git -C "$SITE" config user.name  "podcast-bot"
git -C "$SITE" config user.email "noreply@shipwithai.io"

# A post that does not ship must turn the job red. Without this every failure
# path below `continue`s and the loop ends 0 -- a green tick over a push that
# published nothing, which is worse than no CI at all.
failed=0

for post in "${todo[@]}"; do
  slug="$(basename "$post" .md)"
  locale="$(basename "$(dirname "$post")")"     # en | vi
  id="$slug--$locale"
  draft="$DRAFTS/$id.md"
  stub="$PODCAST/podcasts/$id.podcast.json"

  echo "::group::$id"
  # Stage 4 pushes to the branch that triggered us, so its own commit comes back
  # as a new push. [skip ci] on that commit is the first guard; the podcast-block
  # filter above is the second, because [skip ci] is one careless edit away from
  # a publish storm and a duplicate episode is unrecallable.
  #
  # Drafts live in the content plugin and are gitignored there, so a post can
  # arrive by git while its draft never does.
  if [ ! -f "$draft" ]; then
    echo "BLOCKED: $draft is not on this runner (set DRAFTS_DIR)"; failed=1
    echo "::endgroup::"; continue
  fi

  # Render -> review, retried on a non-ship verdict. The script is authored by an
  # LLM each pass, so a `regenerate` is routine rather than exceptional -- the
  # first CI run tripped on an invented statistic in turn 3. Bounded, because a
  # critic that never says ship must reach a human instead of looping forever.
  #
  # The two non-ship verdicts mean different things and get different retries:
  #   regenerate  the SCRIPT is wrong  -> re-author from the draft, re-render
  #   fix         the AUDIO is wrong   -> re-render the approved script as-is
  # Re-authoring on a `fix` is not just wasteful: it hands the LLM a fresh chance
  # to hallucinate into a script the critic had already passed at 34/35.
  mp3="$PODCAST/podcasts/$id.mp3"
  verdict=""
  for cycle in $(seq 1 "$CYCLES"); do
    echo "[1/4] render (remote server, engine=${ENGINE:-auto})  cycle $cycle/$CYCLES"
    prompt="/content-podcast \"$draft\" --mode dialogue${ENGINE:+ --engine $ENGINE}"
    if [ "$verdict" = "fix" ]; then
      prompt="$prompt

The critic returned 'fix' on the previous cycle: the dialogue script at
podcasts/$id.json is APPROVED as written. Do NOT re-author or edit it. Render
that exact script again, re-run Whisper QA, and re-emit the metadata stub. See
podcast-reports/$id.md for the audio defect being fixed."
    fi
    run "$prompt" || { echo "render failed"; break; }
    # A zero exit does not mean the audio exists. Observed: the agent submitted
    # the render, said it would collect the mp3 "once it comes back", and ended
    # the session -- leaving only the dialogue script. Check the artifact, not
    # the exit code (same reason stage 3 checks the stub, not its exit).
    [ -s "$mp3" ] || {
      echo "NO AUDIO: $mp3 was not produced -- the render stage returned before"
      echo "          the mp3 came back. Nothing to review or publish."
      break; }
    echo "        rendered $(du -h "$mp3" | cut -f1)"

    echo "[2/4] review"
    run "/content-podcast-review $id" || echo "review errored"
    verdict="$(sed -n 's/^verdict:[[:space:]]*//p' \
      "$PODCAST/podcast-reports/$id.critic.yaml" 2>/dev/null | head -1)"
    echo "critic verdict: ${verdict:-<none>}"
    [ "$verdict" = "ship" ] && break
    if [ "$cycle" -lt "$CYCLES" ]; then
      case "$verdict" in
        fix) echo "        re-rendering the approved script (cycle $((cycle+1)))" ;;
        *)   echo "        re-authoring from the draft (cycle $((cycle+1)))" ;;
      esac
    fi
  done

  [ "$verdict" = "ship" ] || {
    echo "HALTED by critic after $CYCLES cycle(s) -- nothing published"
    echo "See podcast-reports/$id.critic.yaml; this one needs a human."
    failed=1; echo "::endgroup::"; continue; }

  echo "[3/4] publish to spotify (no confirm)"
  run "/content-podcast-posting $id --backend spotify-cowork --yes-publish" \
    || echo "posting stage errored"
  kind="$(stub_type "$stub")"
  [ -n "$kind" ] || { echo "NOT PUBLISHED (stub empty) -- no yml attached"; failed=1; echo "::endgroup::"; continue; }
  echo "published ($kind)"

  echo "[4/4] inject yml"
  python3 "$PODCAST/scripts/inject_podcast_frontmatter.py" "$SITE/$post" --stub "$stub" \
    || { echo "inject failed"; failed=1; echo "::endgroup::"; continue; }
  git -C "$SITE" add "$post"
  if git -C "$SITE" commit -qm "content: attach podcast to $slug [skip ci]" \
     && git -C "$SITE" push -q origin "HEAD:$BRANCH"; then
    echo "DONE: $slug shipped with its podcast yml"
  else
    # The episode is live but the post does not reference it -- worth a red tick,
    # since re-running would publish a duplicate rather than fix the frontmatter.
    echo "PUBLISHED BUT NOT COMMITTED: $slug -- attach the yml by hand"
    failed=1
  fi
  echo "::endgroup::"
done

exit "$failed"
