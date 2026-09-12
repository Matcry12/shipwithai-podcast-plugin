---
name: content-podcast-posting
description: Publishes a rendered .mp3 (Spotify for Creators via browser cowork, or Cloudflare R2) and writes the podcast embed block into the metadata stub. Run after /content-podcast-review (ship verdict) and before /content-publish.
---

# content-podcast-posting

Upload a rendered podcast `.mp3` and record the public episode link in the
metadata stub. This is the posting stage — it does not render, does not
review, and does not touch the blog post frontmatter.

## Inputs

Parse from `$ARGUMENTS`: either `<slug>--<locale>` (bare) or `podcasts/<slug>--<locale>.mp3` (mp3
path). Derive `<slug>--<locale>` from whichever form is given.

---

## Backend selection

Parse an optional `--backend` from `$ARGUMENTS`:

- `--backend spotify-cowork` — upload to Spotify for Creators by driving a browser.
  **No env vars required.** This is the default when none of the 5 `PODCAST_R2_*`
  vars are set.
- `--backend r2` — upload to Cloudflare R2 via `scripts/r2_upload.py`. Requires the
  5 `PODCAST_R2_*` env vars. Default when those vars are present.

An explicit `--backend` value always wins. The auto-detection (by presence of the `PODCAST_R2_*` env vars) only chooses the default when `--backend` is omitted. Run only the ONE matching backend section, then go to Step 5.

Parse an optional `--yes-publish` flag (spotify-cowork only):

- **Omitted (default):** the confirm-before-publish gate applies — screenshot the
  filled episode and wait for an explicit human yes before clicking Publish.
- **`--yes-publish` present:** the caller has pre-authorized publication. Skip the
  gate and click Publish without asking. Intended for unattended runs (a push
  listener, a recorded demo) where no human is at the keyboard to answer. Every
  genuine STOP condition below still applies — an auth wall, 2FA, or captcha
  still hands control back rather than guessing.

Only pass `--yes-publish` when a human has authorized this specific run in
advance. It publishes immediately and irreversibly to a public feed.

**Precedence rule — what `--yes-publish` trusts.** The critic's `verdict` in
`podcast-reports/<slug>--<locale>.critic.yaml` is the publish gate, and the
caller (`scripts/ci-podcast.sh`) has already checked it is `ship` before
invoking this skill with `--yes-publish` — re-checking it here is not this
skill's job. Under `--yes-publish`:

- Do **not** open, read, or reason about `podcast-reports/<slug>--<locale>.md`
  (the critic's human-facing prose report). It is not an input to this stage.
- Do **not** withhold or delay publication over advisory language, caveats, or
  suggestions found anywhere in that report ("spot-check by ear before
  publishing", "verify manually", etc). A `ship` verdict already means the
  critic found the content ready to publish; a genuine content defect
  produces a `fix` or `regenerate` verdict, not a caveat riding on a `ship`.
  Second-guessing a `ship` verdict is out of scope for this stage.
- The only conditions that still stop this stage are genuine "a human must
  act" situations, never "the content looks questionable": no browser
  capability, a Spotify auth wall / login / 2FA / captcha, an upload or
  processing error, or the description-editor two-attempt exit (playbook
  step 4). Full list:
  - Step 1 below: rendered MP3 missing.
  - Playbook step 1: no browser capability, or an auth wall / login / 2FA / captcha.
  - Playbook step 3: upload or audio-processing error at Spotify.
  - Playbook step 4: description editor still rejects input after 2 attempts.
  - Playbook step 8: episode published but the embed link can't be confirmed
    after polling — not a publish failure, the episode already went out; only
    the metadata stub is left to finish by hand.

  Nothing else halts an unattended run.

Step 1 (verify the MP3) runs for both. Then branch to the matching backend section.

---

## Step 1 — Verify the rendered MP3 exists

Check that `podcasts/<slug>--<locale>.mp3` exists.

If it does not, **STOP** with:

> "STOP: mp3 not found for `<slug>--<locale>`. Run `/content-podcast <draft-path>` first."

Do not proceed until the file exists.

---

## Step 2 — Backend: spotify-cowork (default, no env vars)

Follow `references/spotify-cowork-playbook.md`. In summary:

1. Confirm a browser capability is available. If not, **STOP**:
   > "STOP: no browser capability available. Use `--backend r2` instead, or run in Cowork."
2. Assemble episode metadata:
   - **Title** — `episodeTitle` from the stub (fall back to the source post's
     frontmatter `title`).
   - **Description** — the post's `description` plus a line linking back to the
     article on the site.
3. Drive the playbook: open Spotify for Creators → check the dashboard for an
   existing draft/published episode with a matching title (reuse it, never
   duplicate — see playbook step 2) → new episode (only if none found) → upload
   `podcasts/<slug>--<locale>.mp3` → fill title/description → on the Review step set **Publish
   date = *Now*** (publish immediately, never *Schedule*) → **confirm-before-publish gate
   (ask the user; never auto-publish — UNLESS `--yes-publish` was passed, which
   pre-authorizes this run and skips the gate per the precedence rule above)** →
   publish now → capture the `open.spotify.com/episode/<id>` link (poll, then
   fall back to asking the user to paste it if Spotify lags).
4. Write the stub:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT:-.}/scripts/podcast_stub.py \
     podcasts/<slug>--<locale>.podcast.json \
     --type spotify \
     --url "<captured episode URL>"
   ```
   (`episodeId` and `embedUrl` are derived from the URL.) Skip to Step 5.

---

## Step 2-R2 — Backend: r2

Verify the 5 `PODCAST_R2_*` env vars are set (`PODCAST_R2_ACCOUNT_ID`,
`PODCAST_R2_ACCESS_KEY`, `PODCAST_R2_SECRET_KEY`, `PODCAST_R2_BUCKET`,
`PODCAST_R2_PUBLIC_BASE`). If any is unset, **STOP**:
> "STOP: R2 credentials missing — export the 5 PODCAST_R2_* vars."
Never hardcode credentials.

Upload, then read the printed public URL:
```bash
python3 ${CLAUDE_PLUGIN_ROOT:-.}/scripts/r2_upload.py podcasts/<slug>--<locale>.mp3 --key <slug>--<locale>.mp3
```
If it exits non-zero, print `STOP: r2 upload failed — <verbatim error>` and stop.

`r2_upload.py` prints a `[upload] PUBLIC_URL <url>` line followed by the bare URL on its own line; use that bare URL as `<public_url>` below.

Write the stub:
```bash
python3 ${CLAUDE_PLUGIN_ROOT:-.}/scripts/podcast_stub.py \
  podcasts/<slug>--<locale>.podcast.json \
  --type audio \
  --url "<public_url>"
```
(For `audio`, `embedUrl` equals `url` and `episodeId` is empty.) Skip to Step 5.

---

## Step 5 — Report to the user

Print a summary:

- Backend used and episode URL or public URL.
- Stub path updated: `podcasts/<slug>--<locale>.podcast.json`.
- Suggested next step:

> "Episode published. The `podcast` block (type + url + embedUrl) is in
> `podcasts/<slug>--<locale>.podcast.json`. Proceed to `/content-publish` (Step 6.5 injects
> the `podcast` block into the post frontmatter so the player renders)."

---

## What this skill does NOT do

- Does not render the episode — run `/content-podcast` for that.
- Does not re-run the review pass — `/content-podcast-review` must have returned
  a `ship` verdict before calling this.
- Does not edit blog post frontmatter — the `podcast` block is written into the
  `.podcast.json` sidecar stub only; `/content-publish` Step 2.5 (SKILL Step 6.5)
  injects it into the EN post's frontmatter before commit + PR.
- Does not require env vars for the spotify-cowork backend — it uses your browser
  session. The r2 backend still requires the 5 `PODCAST_R2_*` vars and stops if any
  is unset.
- Does not auto-publish *by default* — the spotify-cowork backend stops for
  explicit human approval before clicking Publish. Passing `--yes-publish`
  pre-authorizes the run and skips that gate, for unattended callers.
- Does not bypass a missing `.mp3` — if `podcasts/<slug>--<locale>.mp3` is absent, the
  skill stops with a clear message rather than uploading nothing.
- Does not re-adjudicate the critic's verdict under `--yes-publish` — it trusts
  a `ship` verdict already checked by the caller, and does not read
  `podcast-reports/<slug>--<locale>.md` for advisory notes (see the precedence
  rule above).
- Does not create a duplicate Spotify episode on a re-run — the spotify-cowork
  backend checks the dashboard for a matching-title draft or published episode
  before creating a new one (playbook step 2).
