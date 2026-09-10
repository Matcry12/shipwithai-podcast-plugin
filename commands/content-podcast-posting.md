---
name: content-podcast-posting
description: Upload a rendered podcast .mp3 and write the podcast block into the metadata stub. Run after /content-podcast-review passes with a ship verdict.
argument-hint: <slug>--<locale> [--backend spotify-cowork|r2]
---

# /content-podcast-posting

Upload a rendered podcast episode and record the stable audio URL (or Spotify
embed) in the sidecar metadata stub. Delegates the full procedure to the
`content-podcast-posting` skill.

## Usage

```
/content-podcast-posting <slug>--<locale> [--backend spotify-cowork|r2]
/content-podcast-posting podcasts/<slug>--<locale>.mp3 [--backend spotify-cowork|r2]
```

Both slug forms are equivalent. The skill derives `<slug>--<locale>` from whichever is
given.

## Backends

### `--backend spotify-cowork` (DEFAULT — no env vars required)

Uploads the `.mp3` to **Spotify for Creators** (formerly Anchor) via browser
automation.

- **No env vars required.** Uses your existing Spotify for Creators browser
  session; the skill opens/drives the browser and uploads the file.
- **Requires a browser-capable runtime** (a desktop or remote-display
  environment where a browser can open). Fails in headless-only CI.
- **Stops for human confirmation before publishing.** The skill pauses after
  the draft is uploaded and asks you to review the episode details in the
  browser before it clicks Publish. You confirm (or abort) interactively.
- Writes `podcast.type = "spotify"`, `podcast.url`, `podcast.embedUrl`, and
  `podcast.episodeId` into `podcasts/<slug>--<locale>.podcast.json`.

Example:
```
/content-podcast-posting reading-a-review-report--senior-dev--en --backend spotify-cowork
```

### `--backend r2`

Uploads the `.mp3` directly to **Cloudflare R2** (S3-compatible self-hosted
storage, zero egress fees) via `scripts/r2_upload.py`.

- **Requires all five `PODCAST_R2_*` env vars** (see table below). If any is
  unset, the skill stops and asks before proceeding. Never hardcode credentials.
- Fully automated once creds are set; no browser interaction required.
- Writes `podcast.type = "audio"`, `podcast.url`, and `podcast.embedUrl` into
  `podcasts/<slug>--<locale>.podcast.json`.

#### Required env vars (R2 backend only)

| Var | Purpose |
|---|---|
| `PODCAST_R2_ACCOUNT_ID` | Cloudflare account ID. |
| `PODCAST_R2_ACCESS_KEY` | R2 API token Access Key ID. |
| `PODCAST_R2_SECRET_KEY` | R2 API token Secret Access Key. |
| `PODCAST_R2_BUCKET` | R2 bucket name. |
| `PODCAST_R2_PUBLIC_BASE` | Public base URL for the bucket (e.g. `https://assets.example.com`). |

## Pre-conditions

1. `podcasts/<slug>--<locale>.mp3` must already exist — run `/content-podcast` first if
   it does not.
2. `/content-podcast-review` must have returned a `ship` verdict for this slug.
3. EN-only. The podcast pipeline operates on EN drafts only; this posting step
   inherits that constraint.

## What it does

Invokes the `content-podcast-posting` skill, which:

1. Verifies `podcasts/<slug>--<locale>.mp3` exists (fails fast if not).
2. Dispatches the chosen backend:
   - **spotify-cowork:** opens the browser, uploads the mp3 to Spotify for
     Creators, pauses for human confirmation before publishing, and captures
     the episode URL and embed URL.
   - **r2:** checks all five `PODCAST_R2_*` env vars (stops and asks if any is
     unset), runs `scripts/r2_upload.py podcasts/<slug>--<locale>.mp3 --key <slug>--<locale>.mp3`,
     and parses the public URL from the script's stdout.
3. Writes the `podcast` block — `{type, url, embedUrl, episodeId}` — into
   `podcasts/<slug>--<locale>.podcast.json`, preserving all other stub keys.
4. Reports the backend used, public/embed URL, and stub path updated.

## After this command

Proceed to `/content-publish`. Its Step 6.5 reads the stub and injects the
`podcast` block into the post frontmatter before commit+PR, so the website
renders the player automatically.

## Related

- `/content-podcast` — renders the episode; must run before this.
- `/content-podcast-review` — quality gate; must pass (`ship`) before this.
- `/content-publish` — final publish step (Step 6.5 injects the `podcast` block).

## Notes

EN-only. The podcast pipeline operates on EN drafts only; this posting step
inherits that constraint.
