---
name: content-podcast-all
description: Thin orchestrator that sequences the three existing podcast stages — render, review, post — for an EXISTING reviewed+seo'd EN or VI draft (single narrator or `--mode dialogue`). No new render/review/post logic; hard-gates on the review's `ship` verdict before posting. Use when the user says "podcast this draft end-to-end", "render and post the podcast for {slug}", "run the full podcast flow", or invokes `/content-podcast-all`. Wraps `/content-podcast` → `/content-podcast-review` → `/content-podcast-posting --backend spotify-cowork`, preflighting env vars, the `requests` package, the EN/VI locale gate, and the review+SEO precondition before rendering anything. Do NOT invoke this for a generic conversation/podcast/video-generation request, and it does NOT run the blog spine — for generating a blog post (with or without a podcast) from a topic, use `/content-pipeline` (add `--podcast` for the combined flow). This skill only operates on a draft file that already exists and has already passed `/content-review` and `/content-seo`.
---

# content-podcast-all

Sequence the three podcast-stage skills — `/content-podcast` (render),
`/content-podcast-review` (independent quality gate), and
`/content-podcast-posting` (publish) — against one already-written,
already-reviewed draft. This skill contains **no rendering, no critique, and
no posting logic of its own**; every real step happens inside the skill it
delegates to. Its only job is ordering, preflight, and the ship-verdict gate.

## When to invoke

- User says "podcast this draft end-to-end", "render, review, and post the
  podcast for `<slug>`", "run the full podcast flow", or "do the podcast
  pipeline for this post".
- Explicitly invoked by `/content-podcast-all drafts/<slug>--en.md` or
  `drafts/<slug>--vi.md` (optionally with `--mode dialogue`, `--engine`,
  `--voice-name`, `--voice`, `--show`).

## Do NOT invoke

- **Not a generic conversation, podcast, or video-generation skill.** If the
  user wants a podcast/video made from scratch about some topic with no
  existing draft, this is the wrong tool.
- **Does not run the blog spine.** It never calls `/content-idea`,
  `/content-brief`, `/content-write`, `/content-review`, or `/content-seo` —
  it assumes those already ran and checks for their artifacts (see Step 0).
  To generate a blog post (with or without a podcast) starting from a topic,
  use `/content-pipeline "{keyword}" --archetype {id} --locale {id}`, adding
  `--podcast` for the combined blog+podcast flow.
- Not for persona/locale fanout — this skill takes exactly one draft.

## Required inputs

- `draft` (first positional) — path to a reviewed+seo'd draft:
  `drafts/<slug>--en.md` or `drafts/<slug>--vi.md`. Locale is auto-detected
  from the filename suffix, per `/content-podcast` Step 0.

Optional (forwarded verbatim to `/content-podcast`):

- `--mode dialogue` — two-speaker host + co-host episode instead of single
  narrator. See `/content-podcast`'s dialogue rules and voice-clip guards.
- `--engine {kokoro|chatterbox|vieneu|omnivoice}` — render engine override.
  Defaults auto-detect per locale, per `/content-podcast` Step 0.
- `--voice-name`, `--voice`, `--show`, `--out` — same meaning as in
  `/content-podcast`.

## What it does

### 0. PREFLIGHT — fail early, render nothing

Run every check below before touching `/content-podcast`. On the first
failure, **stop immediately**, print the exact fix message, and do not
render, review, or post anything.

1. **Render-server env vars.** `PODCAST_URL` and `PODCAST_TOKEN` must both be
   set. If either is missing:

   > "PODCAST_URL and/or PODCAST_TOKEN are not set. Ask the user for the
   > render server's ngrok URL and bearer token (printed by `start.command`
   > on the Mac host), export them, and re-run `/content-podcast-all`."

2. **`requests` package.** Run `python3 -c "import requests"`. If it fails
   (non-zero exit):

   > "`scripts/call_remote.py` requires the `requests` package. Run
   > `pip install requests` and re-run `/content-podcast-all`."

3. **EN/VI locale gate.** Reuses `/content-podcast` Step 0 wording verbatim:
   the draft filename suffix must be `--en.md` or `--vi.md`, AND the
   frontmatter `locale:` field must agree. If they conflict, or the suffix is
   neither:

   > "Locale gate failed for `<draft>`: the filename suffix must be
   > `--en.md` or `--vi.md` and the frontmatter `locale:` field must agree.
   > Fix the mismatch or point to the correct draft, then re-run
   > `/content-podcast-all`."

4. **Reviewed+seo'd precondition.** The draft must have already passed
   `/content-review` and `/content-seo` (this skill does not run either).
   Check for both terminus artifacts:
   - `review-reports/<slug>.md` exists with a `ship` or `ship-after-fix`
     disposition (not `reject`, and not missing).
   - `seo-reports/<slug>.md` exists with a passing gate verdict (per
     `skills/content-seo/SKILL.md` §Pass criterion: AI Citation Readiness
     `>= 10/15` AND AI Detection risk `<= MEDIUM`).

   If either artifact is missing or not passing:

   > "`<draft>` has not passed `/content-review` and `/content-seo` (missing
   > or non-passing report at `review-reports/<slug>.md` or
   > `seo-reports/<slug>.md`). Run `/content-review` and `/content-seo` on
   > the draft first, then re-run `/content-podcast-all`."

5. **`ffmpeg` on PATH — only when `--mode dialogue`.** Dialogue renders each
   speaker turn separately and concatenates the segments with ffmpeg
   (`scripts/render_dialogue.py`). Without it the run would render every turn
   — N server round-trips — and only then fail at the concat step, wasting the
   whole render. Run `ffmpeg -version`. If it is not found:

   > "`--mode dialogue` needs `ffmpeg` on PATH to concatenate speaker turns,
   > and it was not found. Install it (`brew install ffmpeg` on macOS,
   > `sudo apt install ffmpeg` on Debian/Ubuntu), or drop `--mode dialogue`
   > to render a single narrator, then re-run `/content-podcast-all`."

   Skip this check for single-narrator renders — they never invoke ffmpeg.

6. **Render server reachable.** Env vars being *set* does not mean the server
   is up: the ngrok URL and token rotate every time the host restarts
   `start.command`, so a stale `.env` is the most common real-world failure.
   Probe it before spending a render:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py" health
   ```

   If it fails (non-zero exit, connection error, or 401/403):

   > "The render server did not respond at `$PODCAST_URL`. The ngrok URL and
   > token rotate whenever the host restarts `start.command` — a stale `.env`
   > is the usual cause. Ask for the current URL + token, update `.env`
   > (`set -a; source .env; set +a`), and re-run `/content-podcast-all`."

7. **Cloned-voice env vars — warn, do not block.** For `--mode dialogue` on
   the omnivoice path, host and co-host clips come from
   `PODCAST_<LOCALE>_VOICE` / `_VOICE_2` (and `_REF_TEXT` / `_REF_TEXT_2`).
   If either clip var is unset, the two speakers render with the SAME default
   voice — a finished episode where the dialogue is indistinguishable, which
   is worse than an error because it looks like success. Surface it before
   rendering:

   > "NOTE: `PODCAST_<LOCALE>_VOICE_2` is unset — host and co-host will use
   > the same voice and will not sound distinct. Set the clip vars in `.env`
   > for a real two-speaker episode, or continue if that is acceptable."

   This is a warning, not a gate: rendering proceeds.

All checks pass → proceed to Step 1.

### 1. RENDER

Invoke `/content-podcast <draft> [--mode dialogue] [--engine <engine>]
[--voice-name <name>] [--voice <clip>] [--show <name>] [--out <path>]`,
forwarding every optional flag the user passed. This runs the full
`content-podcast` skill (triage, sayability rewrite, chunker rules,
self-check, render, Whisper QA) and produces `podcasts/<slug>--<locale>.json`,
`podcasts/<slug>--<locale>.mp3`, `podcasts/<slug>--<locale>.transcript.json`,
and the metadata stub `podcasts/<slug>--<locale>.podcast.json`. `<locale>` is
the draft's `--en`/`--vi` suffix; the `<slug>--<locale>` stem is what gets
passed to review and posting below.

If this stage exits non-zero or aborts, stop and report the failure — do not
proceed to review.

### 2. REVIEW — hard gate on `ship`

Invoke `/content-podcast-review <slug>--<locale>`. This dispatches the
independent `podcast-critic` agent and writes
`podcast-reports/<slug>--<locale>.md` with a `ship` / `fix` / `regenerate`
verdict.

**Ordering guard — this is the point of this skill.** Read the verdict:

- **`ship`** → proceed to Step 3.
- **`fix` or `regenerate`** → **do NOT post.** Stop here and report:

  > "Podcast review verdict for `<slug>--<locale>` is `<fix|regenerate>` — not
  > shippable. See `podcast-reports/<slug>--<locale>.md` for the findings.
  > Address them (re-render via `/content-podcast`, or edit the script per the
  > report) and re-run `/content-podcast-review <slug>--<locale>` before
  > posting. `/content-podcast-all` will not post an unreviewed or failing
  > episode."

  Do not loop, retry, or auto-fix on the caller's behalf — `/content-podcast-review`
  already owns its own bounded fix/regenerate loop (2 cycles, per its own
  skill). This skill just refuses to cross the ship/no-ship line.

### 3. POST — only if Step 2 returned `ship`

Invoke `/content-podcast-posting <slug>--<locale> --backend spotify-cowork`.
This keeps `/content-podcast-posting`'s own human confirm-before-publish gate
intact — it stops and asks the user to approve in the browser before
clicking Publish. This skill does not bypass or pre-answer that gate.

If posting fails or the user declines at the confirm gate, report the
failure/decline and stop; do not treat it as fatal to the render/review
artifacts already produced.

### 4. STOP

Report to the user: episode published, backend used, episode URL,
`podcasts/<slug>--<locale>.podcast.json` updated with the `podcast` block.
Tell them:

> "Podcast posted. `/content-publish` will read
> `podcasts/<slug>--<locale>.podcast.json` and auto-inject the `podcast`
> embed block into the post's frontmatter — run it when ready to publish
> the post."

**Do not run the blog spine.** This skill stops here; it never invokes
`/content-idea`, `/content-brief`, `/content-write`, `/content-review`,
`/content-seo`, or `/content-publish` itself.

## Errors

Hard aborts (Step 0, before any render):

- `PODCAST_URL` or `PODCAST_TOKEN` unset.
- `python3 -c "import requests"` fails.
- Draft fails the EN/VI locale gate (suffix/frontmatter mismatch or missing).
- Draft missing a passing `review-reports/<slug>.md` or `seo-reports/<slug>.md`.
- `draft` argument missing entirely → exit with usage.

Mid-flow (after Step 0 passes):

- `/content-podcast` exits non-zero or aborts internally (e.g. its own VI
  voice-quality or dialogue-clip guards) → stop, report the stage and reason.
  No podcast artifacts to post.
- `/content-podcast-review` verdict is `fix` or `regenerate` → hard stop, no
  posting. See Step 2.
- `/content-podcast-posting` fails, or the user declines the Spotify confirm
  gate → stop, report; render + review artifacts are preserved for a manual
  retry of posting alone.

This skill never retries a failed stage automatically and never silently
skips the review gate. It is not best-effort like `content-pipeline`'s
optional `--podcast` stage — here the podcast IS the task, so a failure is
reported directly rather than logged-and-continued.

## Related

- `/content-podcast` — Step 1; render.
- `/content-podcast-review` — Step 2; independent quality gate this skill
  hard-gates on.
- `/content-podcast-posting` — Step 3; publish (Spotify, with its own human
  confirm gate).
- `/content-pipeline` — the blog spine; use its `--podcast` flag for a
  combined "topic to published post + podcast" run. This skill is the
  narrower "I already have a reviewed draft, just do the podcast" tool.
- `/content-publish` — run separately, afterward, by the user; injects the
  `podcast` block this skill's Step 3 fills.
