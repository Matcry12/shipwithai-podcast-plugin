#!/usr/bin/env bash
# Demo listener: a pushed blog on the website repo triggers the full podcast
# chain unattended, and the post gets its podcast: yml pushed back.
#
# Fully autonomous. The only approval is the podcast-critic's verdict, read
# from critic.yaml. Stage 3 passes --yes-publish, which pre-authorizes the
# Spotify publish and skips the confirm gate -- so this script publishes
# irreversibly to a PUBLIC feed with no human check. Run it only when you
# intend exactly that.
#
#   bash scripts/demo-podcast-listener.sh --dry   # rehearse: no claude, no push
#   bash scripts/demo-podcast-listener.sh
set -uo pipefail

SITE="${SITE_REPO:-$HOME/Developer/shipwithai.io}"
PLUGIN="${PLUGIN_REPO:-$HOME/Developer/shipwithai-content-agent-plugin}"
BRANCH="${DEMO_BRANCH:-demo/podcast-auto}"
STATE="$SITE/.demo-podcast.sha"
PERM_MODE="${DEMO_PERM_MODE:-bypassPermissions}"
VIDEOMAKER="${VIDEOMAKER_ROOT:-$HOME/Documents/Video maker}"
export VIDEOMAKER_ROOT="$VIDEOMAKER"
DRY=false
[ "${1:-}" = "--dry" ] && DRY=true

sha() { git -C "$SITE" ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1; }

# ponytail: one wrapper so every stage gets identical env + permission flags.
run() { ( cd "$PLUGIN" && claude -p --permission-mode "$PERM_MODE" "$1" ); }

# Render writes type:"" ; posting fills it. Checking the stub is how we know the
# publish actually landed -- a zero exit from the posting stage doesn't prove it.
stub_type() {
  python3 - "$1" <<'PY' 2>/dev/null
import json,sys
try: print(json.load(open(sys.argv[1]))["podcast"]["type"] or "", end="")
except Exception: pass
PY
}

if ! $DRY; then
  set -a; . "$PLUGIN/.env" 2>/dev/null; set +a
  printf 'claude auth ... '
  claude -p "reply with the single word: ok" >/dev/null 2>&1 \
    && echo ok || { echo FAILED; echo "run 'claude login' first"; exit 1; }
  printf 'local kokoro ... '
  [ -x "$VIDEOMAKER/.venv/bin/python" ] && [ -f "$VIDEOMAKER/assets/models/kokoro/kokoro-v1.0.onnx" ] \
    && echo "ok (no render server needed)" \
    || { echo "MISSING - set VIDEOMAKER_ROOT to the Video-maker checkout"; exit 1; }
  printf 'ffmpeg ... '
  command -v ffmpeg >/dev/null && echo ok || { echo "MISSING"; exit 1; }
  printf 'browser for spotify ... '
  command -v browser-harness >/dev/null && echo ok \
    || { echo "browser-harness NOT on PATH"; exit 1; }
  echo
  echo "!! --yes-publish is ON: episodes go live on Spotify with no confirm."
  echo
fi

base="$(sha)"
[ -n "$base" ] || { echo "branch $BRANCH not on origin - run the prep step first"; exit 1; }
echo "$base" > "$STATE"
echo "watching $BRANCH in $(basename "$SITE") every 10s $($DRY && echo '(DRY RUN)')"
echo "baseline: ${base:0:8}"

while true; do
  new="$(sha)"; prev="$(cat "$STATE")"
  if [ -n "$new" ] && [ "$new" != "$prev" ]; then
    echo "[$(date +%T)] push detected: ${new:0:8}"
    git -C "$SITE" pull --ff-only --quiet origin "$BRANCH" || echo "  !! pull failed"

    arrived=()
    mapfile -t arrived < <(git -C "$SITE" diff --name-only "$prev" "$new" \
      -- 'src/content/blog/en/*.md' 2>/dev/null)

    for post in ${arrived+"${arrived[@]}"}; do
      slug="$(basename "$post" .md)"; id="$slug--en"
      draft="drafts/$id.md"; stub="$PLUGIN/podcasts/$id.podcast.json"
      [ -f "$PLUGIN/$draft" ] || { echo "  BLOCKED: $slug -- no $draft here"; continue; }
      # Stage 5 pushes to the branch we watch, so our own yml commit comes back
      # as a "new blog". Without this the listener re-renders and publishes a
      # DUPLICATE Spotify episode every cycle, forever. A post that already has
      # a podcast block is done - that is true across restarts too.
      grep -q '^podcast:' "$SITE/$post" \
        && { echo "  SKIP: $slug already has a podcast block"; continue; }
      echo "  NEW BLOG: $slug"

      if $DRY; then
        echo "    1 render : /content-podcast $draft --engine kokoro --mode dialogue --local"
        echo "    2 review : /content-podcast-review $id      -> gate on critic verdict"
        echo "    3 post   : /content-podcast-posting $id --backend spotify-cowork --yes-publish"
        echo "    4 inject : inject_podcast_frontmatter.py $post --stub podcasts/$id.podcast.json"
        echo "    5 push   : git commit + push $BRANCH"
        continue
      fi

      echo "  [1/4] rendering (kokoro)"
      run "/content-podcast $draft --engine kokoro --mode dialogue --local" \
        || { echo "  !! render failed"; continue; }

      echo "  [2/4] review"
      run "/content-podcast-review $id" || echo "  !! review errored"
      # The critic's verdict is the only approval in this pipeline.
      verdict="$(sed -n 's/^verdict:[[:space:]]*//p' \
        "$PLUGIN/podcast-reports/$id.critic.yaml" 2>/dev/null | head -1)"
      echo "        critic verdict: ${verdict:-<none>}"
      [ "$verdict" = "ship" ] || { echo "  HALTED by critic (not ship) - nothing published"; continue; }

      echo "  [3/4] publishing to spotify (no confirm)"
      run "/content-podcast-posting $id --backend spotify-cowork --yes-publish" \
        || echo "  !! posting stage errored"
      kind="$(stub_type "$stub")"
      [ -n "$kind" ] || { echo "  NOT PUBLISHED (stub still empty) - no yml attached"; continue; }
      echo "        published ($kind)"

      echo "  [4/4] injecting yml"
      python3 "$PLUGIN/scripts/inject_podcast_frontmatter.py" \
        "$SITE/$post" --stub "$stub" || continue
      git -C "$SITE" add "$post"
      git -C "$SITE" commit -qm "content: attach podcast to $slug" \
        && git -C "$SITE" push -q origin "$BRANCH" \
        && echo "  DONE: $slug shipped with its podcast yml"
    done
    # Re-read the head: our own push above moved it, and recording the OLD sha
    # would wake us again next tick. ponytail: a writer pushing in this exact
    # gap would be skipped - the podcast-block guard above is what actually
    # prevents duplicate episodes, this just keeps the log quiet.
    echo "$(sha)" > "$STATE"
  fi
  sleep 10
done
