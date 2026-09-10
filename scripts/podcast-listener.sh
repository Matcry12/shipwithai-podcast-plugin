#!/usr/bin/env bash
# podcast-listener.sh — wake on a push to the remote, queue drafts that passed
# SEO but have no podcast yet.
#
#   bash scripts/podcast-listener.sh --once     # print the queue and exit
#   bash scripts/podcast-listener.sh            # watch (poll remote every 2 min)
#   bash scripts/podcast-listener.sh --run      # watch, and render+review each hit
#
# --run processes at most $PODCAST_MAX_PER_PUSH drafts per push (default 3).
# Without a cap, one push against a cold queue would fire ~96 renders.
#
# Posting to Spotify is deliberately NOT automated — it has a human gate.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${PODCAST_WATCH_BRANCH:-master}"
INTERVAL="${PODCAST_POLL_SECONDS:-120}"
STATE="$REPO/.podcast-listener.sha"
MAX="${PODCAST_MAX_PER_PUSH:-3}"

# ponytail: the Composio GITHUB_BRANCH_CHANGED_TRIGGER is poll-type on a 2-min
# interval, so `git ls-remote` is the same signal with no auth and no daemon.
# Swap this one function if you move to `composio dev listen`.
remote_sha() { git -C "$REPO" ls-remote origin "refs/heads/$BRANCH" | cut -f1; }

# A draft is queued when it passed SEO but has no podcast artifact.
# Stems match exactly: /content-podcast strips the --<locale> suffix to form
# <slug>, then writes podcasts/<slug>--<locale>.*  — which is the same stem.
queue() {
  local stem
  for f in "$REPO"/seo-reports/*.md; do
    [ -e "$f" ] || continue
    stem="$(basename "$f" .md)"
    [ -f "$REPO/podcasts/$stem.podcast.json" ] && continue        # already done
    [ -f "$REPO/drafts/$stem.md" ] || continue                    # see blocked()
    echo "$stem"
  done
}

# Passed SEO, no podcast, but the draft is not on this machine. drafts/ is
# gitignored, so a NEW draft never arrives by git - only its seo-report does.
# These would be silently skipped, so surface them instead.
blocked() {
  local stem
  for f in "$REPO"/seo-reports/*.md; do
    [ -e "$f" ] || continue
    stem="$(basename "$f" .md)"
    [ -f "$REPO/podcasts/$stem.podcast.json" ] && continue
    [ -f "$REPO/drafts/$stem.md" ] && continue
    echo "$stem"
  done
}

render_and_review() {
  local stem="$1"
  echo "  -> rendering $stem"
  claude -p "/content-podcast drafts/$stem.md" \
    && claude -p "/content-podcast-review $stem" \
    || echo "  !! failed: $stem (continuing)"
}

case "${1:-}" in
  --once)
    queue
    exit 0
    ;;
esac

RUN=false
[ "${1:-}" = "--run" ] && RUN=true

echo "watching origin/$BRANCH every ${INTERVAL}s (run=$RUN)"
[ -f "$STATE" ] || remote_sha > "$STATE"

while true; do
  new="$(remote_sha)"
  if [ "$new" != "$(cat "$STATE")" ]; then
    prev="$(cat "$STATE")"
    echo "[$(date -u +%H:%M:%S)] push detected: ${new:0:8}"
    # ponytail: pull, not fetch - fetch updates refs only, so queue() would
    # read a stale working tree and never see the blog that was just pushed.
    git -C "$REPO" pull --ff-only --quiet origin "$BRANCH" \
      || echo "  !! pull failed (dirty tree or diverged) - queue may be stale"
    # The blogs that arrived in THIS push. A bare queue count says "41 waiting";
    # this says which blog just landed, which is the signal a human acts on.
    mapfile -t arrived < <(git -C "$REPO" diff --name-only "$prev" "$new" -- seo-reports/ 2>/dev/null \
      | sed -n 's#^seo-reports/\(.*\)\.md$#\1#p')
    for s in ${arrived+"${arrived[@]}"}; do
      if [ -f "$REPO/podcasts/$s.podcast.json" ]; then
        echo "  new blog: $s -- already has a podcast, skipping"
      elif [ -f "$REPO/drafts/$s.md" ]; then
        echo "  NEW BLOG READY: $s"
      else
        echo "  NEW BLOG BLOCKED: $s -- draft not on this machine"
      fi
    done
    mapfile -t hits < <(queue)
    mapfile -t noskip < <(blocked)
    [ "${#noskip[@]}" -gt 0 ] && printf '  WARNING: %s passed SEO but the draft is not on this machine (gitignored, cannot render)\n' "${#noskip[@]}"
    if [ "${#hits[@]}" -eq 0 ]; then
      echo "  nothing new to podcast"
    else
      echo "  ${#hits[@]} queued"
      printf '  queued: %s\n' "${hits[@]}"
      if $RUN; then
        if [ "${#hits[@]}" -gt "$MAX" ]; then
          echo "  capped at $MAX this push (${#hits[@]} waiting) - raise PODCAST_MAX_PER_PUSH to change"
          hits=("${hits[@]:0:$MAX}")
        fi
        for s in "${hits[@]}"; do render_and_review "$s"; done
      fi
    fi
    echo "$new" > "$STATE"
  fi
  sleep "$INTERVAL"
done
