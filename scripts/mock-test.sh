#!/usr/bin/env bash
# mock-test.sh — prove the listener chain end to end without a render server.
#
#   bash scripts/mock-test.sh
#
# Fakes a blogger finishing a post, fakes the renderer, and checks the post
# moves: blocked -> queued -> done. Cleans up after itself.
set -uo pipefail
cd "$(dirname "$0")/.."

# "0000-" makes it sort first, so MAX=1 renders OUR slug and nothing else.
SLUG="0000-mocktest--pm--essay--en"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" drafts/"$SLUG".md seo-reports/"$SLUG".md podcasts/"$SLUG".podcast.json .podcast-listener.sha' EXIT

pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1)); else echo "  FAIL  $1 (want '$3', got '$2')"; fail=$((fail+1)); fi; }

# Fake `claude`. Writes an artifact ONLY for our slug - a stub that renders
# anything would carpet podcasts/ with fakes for every real draft.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<STUB
#!/usr/bin/env bash
for a in "\$@"; do
  case "\$a" in
    -p) ;;
    *"/content-podcast drafts/$SLUG.md")
      echo '{"mock":true}' > "podcasts/$SLUG.podcast.json"
      echo "    [stub] rendered $SLUG" ;;
    *"/content-podcast-review $SLUG") echo "    [stub] reviewed (verdict: ship)" ;;
    *) echo "    [stub] REFUSED (not the mock slug): \$a"; exit 1 ;;
  esac
done
STUB
chmod +x "$TMP/bin/claude"

echo "== 1. blogger pushes an seo-report; the draft is gitignored =="
printf 'mock\n' > seo-reports/"$SLUG".md
check "blocked (no draft on this machine)" "$(bash scripts/podcast-listener.sh --once | grep -c "$SLUG")" "0"

echo "== 2. the draft reaches this machine =="
printf -- '---\nlocale: en\n---\nmock body\n' > drafts/"$SLUG".md
check "now in the ready queue" "$(bash scripts/podcast-listener.sh --once | grep -c "$SLUG")" "1"

echo "== 3. a push wakes the listener, which renders it =="
echo "0000000000000000000000000000000000000000" > .podcast-listener.sha
PATH="$TMP/bin:$PATH" PODCAST_POLL_SECONDS=2 PODCAST_MAX_PER_PUSH=1 \
  PODCAST_WATCH_BRANCH="$(git rev-parse --abbrev-ref HEAD)" \
  timeout 25 bash scripts/podcast-listener.sh --run > "$TMP/out.log" 2>&1
grep -q 'push detected' "$TMP/out.log" || { echo "--- listener output ---"; cat "$TMP/out.log"; }
check "listener detected the push" "$(grep -c 'push detected' "$TMP/out.log")" "1"
check "renderer ran for our slug"  "$(grep -c "\[stub\] rendered $SLUG" "$TMP/out.log")" "1"
check "no other draft was touched" "$(grep -c 'REFUSED' "$TMP/out.log")" "0"
check "artifact was written"       "$([ -f podcasts/"$SLUG".podcast.json ] && echo yes || echo no)" "yes"

echo "== 4. done, so it leaves the queue =="
check "no longer queued" "$(bash scripts/podcast-listener.sh --once | grep -c "$SLUG")" "0"

echo
echo "passed: $pass   failed: $fail"
[ "$fail" -eq 0 ]
