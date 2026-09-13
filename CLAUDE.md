# CLAUDE.md — Working inside the podcast plugin

This repo turns a reviewed blog draft into a published podcast episode. It was
split out of `shipwithai-content-agent-plugin`, which still owns blog writing
and still produces the drafts this consumes.

## The chain

```
drafts/<slug>--<locale>.md          written elsewhere (see Inputs)
  /content-podcast                  rewrite for the ear -> render -> Whisper QA
  /content-podcast-review           independent critic, scored, hard gate
  /content-podcast-posting          publish to Spotify (browser) or R2
  inject_podcast_frontmatter.py     write podcast: back into the blog post
```

`/content-podcast-all` runs the first three in order and hard-gates on the
review verdict. It deliberately **never auto-publishes** — its posting stage
keeps the human confirm. Automation therefore calls the three stages
separately, so it can pass `--yes-publish`. See `scripts/ci-podcast.sh`.

## Inputs this repo does not own

In CI the input is the blog post itself: `ci-podcast.sh` copies it from the
site checkout into `drafts/<slug>--<locale>.md`, the shape `/content-podcast`
expects. Nothing about the post's content has to exist on the runner ahead of
time. (Running the command by hand still takes any file of that shape.)

Voice clips (`PODCAST_EN_VOICE` etc.) live outside both repos. Without them EN
silently falls back to kokoro presets — the episodes still render, they just
stop sounding like the show. Check `runner-doctor.sh` output before blaming the
pipeline.

## Prime directives

1. **Never pass `--yes-publish` casually.** It skips the confirm and publishes
   irreversibly to a public feed. A duplicate episode cannot be recalled — only
   deleted by hand in the Spotify dashboard. In CI the critic's `ship` verdict
   is the only remaining gate.
2. **The engine is auto-detected; do not force it.** EN with voice clips
   configured resolves to `omnivoice` (cloned voices) — the main path. `kokoro`
   is the *fallback* for when they are not, and `--local` is a demo shortcut.
   Forcing either silently downgrades the product.
3. **Verify artifacts, never exit codes.** A stage can return 0 having produced
   nothing: the render agent has twice submitted a job, promised to collect the
   mp3 later, and ended the session. Check that the file exists.
4. **Two loop guards, both required.** The final stage commits to the branch the
   workflow watches. `[skip ci]` on that commit, *and* skip any post already
   carrying a `podcast:` block. `[skip ci]` alone is one careless edit from a
   publish storm.

## Running it unattended

`scripts/ci-podcast.sh` is the CI entry point, driven by `.github/workflows/podcast.yml`
in the **site** repo on a **self-hosted** runner. Self-hosted is not a
preference: the drafts are gitignored, the TTS model is remote-but-LAN, and
Spotify has no publishing API so the posting stage drives a logged-in browser.
No cloud runner can supply any of the three.

Before registering a runner anywhere, run `scripts/runner-doctor.sh`. It checks
every dependency that has actually broken a run and prints the fix.

## What NOT to do

- Don't re-add blog-writing commands here. If a change is about briefs, drafts,
  personas or SEO, it belongs in the content plugin.
- Don't commit `podcasts/` or `podcast-reports/`. The durable record of an
  episode is the `podcast:` block in the published post.
- Don't assume `claude -p` can background work. It terminates the moment the
  agent returns; a backgrounded render is simply lost.
