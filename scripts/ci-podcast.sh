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
((BASH_VERSINFO[0] >= 4)) || { echo "bash >= 4 required (macOS /bin/bash is 3.2: brew install bash, put /opt/homebrew/bin first on PATH)"; exit 1; }

SITE="${SITE_REPO:?SITE_REPO not set}"
# This repo. Everything the pipeline produces (podcasts/, podcast-reports/)
# lives here.
PODCAST="${PODCAST_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"

# Sourced here, before anything below resolves a *_DIR/*_MODE/*_MAX/*_ENGINE
# default -- bash fills in a ${VAR:-default} at the point of assignment, so
# sourcing .env any later would silently discard whatever it sets for those
# vars (only vars read directly at point-of-use, like PODCAST_URL/TOKEN
# below, would still pick it up).
set -a; . "$PODCAST/.env" 2>/dev/null; set +a

# The render skill wants its input as drafts/<slug>--<locale>.md (the locale
# suffix is how it picks the voice pair). The post in the checkout is that same
# file under the site's naming, so it is copied into place per run -- no second
# copy of the content has to be kept in sync on the runner.
DRAFTS="$PODCAST/drafts"
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
# "Arrived" means posts ADDED or MODIFIED by commits the blogger put on this
# branch -- not a tree diff of BEFORE..AFTER. A tree diff of a merge (or a
# rebase + force-push) of master into a demo branch lists every post master
# gained since the branch forked (125 today), and the cap would then publish
# the first three alphabetically, unchosen and unrecallable. So: first-parent
# walk (drops the merged-in side), no merge commits, nothing already on master
# (drops the rebased-onto side), added/modified only (a deleted post has no
# file to render from). A brand-new branch (BEFORE all-zeros) or a BEFORE this
# clone can no longer see both reduce to "everything on the branch that is
# not on master". core.quotePath=false so a non-ASCII filename comes back
# literal rather than C-escaped and unmatchable.
ZERO=0000000000000000000000000000000000000000
range="$BEFORE..$AFTER"
{ [ "$BEFORE" = "$ZERO" ] || ! git -C "$SITE" cat-file -e "$BEFORE^{commit}" 2>/dev/null; } && range="$AFTER"
mapfile -t arrived < <(git -C "$SITE" -c core.quotePath=false log --first-parent --no-merges \
    --diff-filter=AM --name-only --pretty=format: "$range" ^origin/master \
    -- 'src/content/blog/en/*.md' 'src/content/blog/vi/*.md' | grep -v '^$' | sort -u)

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

# A post that does not ship must turn the job red. Without this every failure
# path below `continue`s and the loop ends 0 -- a green tick over a push that
# published nothing, which is worse than no CI at all.
failed=0

if [ "${#todo[@]}" -gt "$MAX" ]; then
  # The dropped posts only come back if someone edits them again, so this is
  # a red tick with their names, not a note nobody reads.
  for post in "${todo[@]:$MAX}"; do echo "::warning::$(basename "$post" .md) NOT processed -- push capped at $MAX (PODCAST_MAX_PER_PUSH); edit it again to retry"; done
  todo=("${todo[@]:0:$MAX}")
  failed=1
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

for post in "${todo[@]}"; do
  slug="$(basename "$post" .md)"
  # Some posts are named <slug>--en.md already; without this the id would be
  # <slug>--en--en and an agent that "normalises" it writes the mp3 elsewhere.
  slug="${slug%--en}"; slug="${slug%--vi}"
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
  # Everything under podcasts/ and podcast-reports/ persists on this runner
  # across pushes. Two cases:
  #  - the stub already carries a link: a previous run published this post
  #    and then failed to commit the yml (push rejected, job killed). Do not
  #    render, review or publish again -- inject the link it has.
  #  - anything else is stale and must go, or a critic.yaml from last week
  #    supplies a `ship` for audio nobody reviewed when this run's review
  #    stage errors out, and last week's mp3 satisfies the artifact check.
  kind="$(stub_type "$stub")"
  if [ -n "$kind" ]; then
    echo "already published ($kind) by an earlier run -- stub has the link; injecting only"
  else
  rm -f "$PODCAST/podcasts/$id".* "$PODCAST/podcast-reports/$id".*
  mkdir -p "$DRAFTS" && cp "$SITE/$post" "$draft" \
    || { echo "cannot copy $post into drafts/"; failed=1; echo "::endgroup::"; continue; }

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
    prompt="/content-podcast \"$draft\" --mode dialogue${ENGINE:+ --engine $ENGINE}

Use the draft's frontmatter title VERBATIM as episodeTitle in the metadata
stub (do not rephrase or make it 'sayable'): the posting stage recognises an
already-published episode by exact title match, so the title must be the same
on every render of this post.

FAITHFULNESS RULE (hard fail downstream): never state a number, duration,
size, line count, percentage, price or comparison that is not literally in the
draft -- not as a hook, not as an estimate, not as colour. 'takes five
minutes', 'about three lines', 'twice as fast' with no such figure in the draft
each cost a whole render cycle today. When tempted, say it qualitatively
('a short script', 'quickly') or cut it. Before you finish, re-read every
sentence containing a digit or a number word and confirm it is in the draft."
    case "$verdict" in
      fix)
        # Keep the script, apply the critic's listed edits, re-render. 'fix'
        # covers two cases (see agents/podcast-critic.md): small script issues
        # the critic already wrote the exact edit for, or audio missing content
        # the script has. Either way the script is patched, not re-authored.
        # Telling the agent the script was "approved as written" made it refuse
        # the cycle outright when the report listed script edits (2026-09-13).
        rm -f "$mp3" "$PODCAST/podcasts/$id.transcript.json"
        prompt="$prompt

The critic returned 'fix' on the previous cycle. Keep the existing dialogue
script at podcasts/$id.json -- do NOT re-author it from the draft. Open
podcast-reports/$id.critic.yaml and apply exactly the edits in each item's
'fix:' line (majors, minors, nits) to that script, nothing more. If an item is
a render defect (audio missing words the script has), the script needs no
change for it. Keep turns strictly alternating host / cohost while applying
them. Then render the patched script, re-run Whisper QA, and re-emit the
metadata stub." ;;
      regenerate)
        # The script itself is wrong, so nothing from the last cycle may survive.
        # The skill skips authoring when it finds existing artifacts that pass
        # QA -- sensible by hand, fatal here: observed 2026-09-12, cycle 2
        # "rendered" in 27 seconds by reusing cycle 1's script, reviewed the same
        # text, and drew the same regenerate. Clear everything so it must author.
        # Keep the script this time. Re-authoring from scratch after an
        # invented figure produced a *different* invented figure on the next
        # cycle, twice in a row (2026-09-13: 'five minutes', then 'three
        # lines'). The critic writes an exact fix for every blocker; applying
        # it is one edit with no new dice roll. Only a structural failure
        # (the report says the conversation itself failed) needs a rewrite.
        # The stub stays: its podcast block is empty until publish, and the
        # review stage refuses to run without it (observed when it was removed).
        rm -f "$mp3" "$PODCAST/podcasts/$id".transcript.json
        prompt="$prompt

The critic returned 'regenerate' on the previous cycle. Open
podcast-reports/$id.critic.yaml. For every item under blockers, majors, minors
and nits, apply the edit in its 'fix:' line to the EXISTING script at
podcasts/$id.json -- remove or replace the flagged claim exactly as the fix
says, and change nothing else. Do NOT author a fresh script from the draft
unless a blocker says the dialogue structure itself failed (two monologues,
no conversation); a fresh authoring has reintroduced a new invented figure
every time it was tried. INVARIANT the fixes may not break: turns strictly
alternate host / cohost, the cohost asks and the host explains. If a fix line
would put two consecutive turns in the same voice (a critic once said
'reassign turn 9 to cohost' while turn 10 already was), reassign the adjacent
turn so the pattern holds rather than applying the fix literally. Then render,
re-run Whisper QA, re-emit the stub." ;;
    esac
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
    # A review that errors out must yield NO verdict, not last cycle's. With
    # the file left in place an errored cycle 2 re-read cycle 1's regenerate
    # and burned the loop on a script that had already been patched.
    rm -f "$PODCAST/podcast-reports/$id.critic.yaml"
    run "/content-podcast-review $id" || echo "review errored"
    verdict="$(sed -n 's/^verdict:[[:space:]]*//p' \
      "$PODCAST/podcast-reports/$id.critic.yaml" 2>/dev/null | head -1)"
    echo "critic verdict: ${verdict:-<none>}"
    [ "$verdict" = "ship" ] && break
    if [ "$cycle" -lt "$CYCLES" ]; then
      case "$verdict" in
        fix) echo "        patching the script per critic and re-rendering (cycle $((cycle+1)))" ;;
        *)   echo "        removing the flagged claims from the script and re-rendering (cycle $((cycle+1)))" ;;
      esac
    fi
  done

  [ "$verdict" = "ship" ] || {
    echo "HALTED after $cycle cycle(s), last verdict ${verdict:-<none>} -- nothing published"
    echo "See podcast-reports/$id.critic.yaml; this one needs a human."
    failed=1; echo "::endgroup::"; continue; }

  # GitHub can mark this run "completed" (timeout/lost heartbeat) while a
  # network blip leaves the runner itself still executing -- the render+review
  # cycles above are the likeliest place to lose minutes of connectivity. A
  # human seeing that red run would rerun the push, which would publish a
  # second episode for the same post. Cheap re-check right before the
  # irreversible step; does not fix the network loss itself, and no-ops (same
  # as before this check existed) when gh is missing/unauthenticated or this
  # is a local, non-Actions run.
  if [ -n "${GITHUB_RUN_ID:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ]; then
    run_status="$(gh run view "$GITHUB_RUN_ID" -R "$GITHUB_REPOSITORY" --json status -q .status 2>/dev/null)"
    if [ "$run_status" != "in_progress" ]; then
      echo "ABORT: cannot confirm this run is still live on GitHub (status '${run_status:-unreadable}') -- refusing to publish, a rerun would risk a duplicate episode"
      failed=1; echo "::endgroup::"; continue
    fi
    # The job timeout kills the process tree wherever it is. Landing between
    # the Publish click and the stub write leaves a live episode with no
    # record and no log line. Do not start a publish that cannot finish.
    if [ "$SECONDS" -gt $(( (${JOB_TIMEOUT_MIN:-90} - 15) * 60 )) ]; then
      echo "ABORT: $((SECONDS/60)) min elapsed of a ${JOB_TIMEOUT_MIN:-90} min job -- too little left to publish safely; rerun the push"
      failed=1; echo "::endgroup::"; continue
    fi
  fi

  echo "[3/4] publish to spotify (no confirm)"
  mkdir -p "$PODCAST/podcast-reports"
  run "/content-podcast-posting $id --backend spotify-cowork --yes-publish" \
    2>&1 | tee "$PODCAST/podcast-reports/$id.posting.log" || echo "posting stage errored"
  kind="$(stub_type "$stub")"
  if [ -z "$kind" ]; then
    # The playbook's step-8 outcome: the Publish click went through but the
    # share link could not be read back. Saying NOT PUBLISHED here invites a
    # rerun and a duplicate; the recovery is a hand-written stub, not a rerun.
    if grep -q 'STOP: episode published' "$PODCAST/podcast-reports/$id.posting.log"; then
      echo "PUBLISHED, LINK UNCONFIRMED: $slug is live on Spotify but the stub is empty. Do NOT rerun. Copy the episode URL from the dashboard and run: python3 scripts/podcast_stub.py $stub --type spotify --url <url>, then push any edit to the post."
    else
      echo "NOT PUBLISHED (stub empty) -- no yml attached"
    fi
    failed=1; echo "::endgroup::"; continue
  fi
  echo "published ($kind)"
  fi   # not already published

  echo "[4/4] inject yml"
  python3 "$PODCAST/scripts/inject_podcast_frontmatter.py" "$SITE/$post" --stub "$stub" \
    || { echo "inject failed"; failed=1; echo "::endgroup::"; continue; }
  commit_push() {
    git -C "$SITE" add "$post" \
      && git -C "$SITE" commit -qm "content: attach podcast to $slug [skip ci]" \
      && git -C "$SITE" push -q origin "HEAD:$BRANCH"
  }
  # A blogger pushing during the 30-60 min this job runs makes the first push
  # non-fast-forward. Take their branch head, put the yml on their version of
  # the post, push again. Once: the stub keeps the link, and the next push to
  # this post takes the "already published" path above.
  if commit_push; then
    echo "DONE: $slug shipped with its podcast yml"
  elif echo "        branch moved during the run; re-attaching on its new head" \
       && git -C "$SITE" fetch -q origin "$BRANCH" && git -C "$SITE" reset -q --hard FETCH_HEAD \
       && python3 "$PODCAST/scripts/inject_podcast_frontmatter.py" "$SITE/$post" --stub "$stub" \
       && commit_push; then
    echo "DONE: $slug shipped with its podcast yml (second attempt)"
  else
    # The episode is live but the post does not reference it -- worth a red
    # tick. The stub still holds the link, so the next push to this post
    # injects it without publishing again.
    echo "PUBLISHED BUT NOT COMMITTED: $slug -- push any edit to the post to attach the yml, or attach it by hand"
    failed=1
  fi
  echo "::endgroup::"
done

exit "$failed"
