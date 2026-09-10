---
name: content-podcast-all
description: Render, review, and post a Spotify podcast episode for an EXISTING reviewed+seo'd EN or VI draft (single narrator or --mode dialogue) in one command, hard-gating on the review's ship verdict before posting. Do NOT use for a generic conversation/podcast/video-generation request, and does NOT run the blog spine — to generate a blog post (with or without a podcast) from a topic, use /content-pipeline (add --podcast for the combined flow).
argument-hint: drafts/<slug>--en.md|--vi.md [--mode dialogue] [--engine kokoro|chatterbox|vieneu|omnivoice] [--voice-name af_heart] [--show "Name"]
---

# /content-podcast-all

Sequence the three existing podcast commands — render, review, post — for
one draft that has already passed `/content-review` and `/content-seo`.
Delegates the full procedure to the `content-podcast-all` skill. This
command adds **no** new render/review/post logic; it only orders the three
existing commands and hard-gates on the review verdict.

```
/content-podcast   →   /content-podcast-review   →   /content-podcast-posting
 (render)               (independent quality gate)     (Spotify, human confirm)
```

## Usage

```
/content-podcast-all drafts/<slug>--en.md
/content-podcast-all drafts/<slug>--vi.md
/content-podcast-all drafts/<slug>--en.md --mode dialogue
/content-podcast-all drafts/<slug>--en.md --engine kokoro --voice-name af_heart
```

## Arguments

| Arg | Required | Default | Meaning |
|---|---|---|---|
| `drafts/<slug>--en.md` or `drafts/<slug>--vi.md` (first positional) | yes | — | Path to the reviewed+seo'd draft. Locale auto-detected from the `--en`/`--vi` suffix, matched against frontmatter `locale:` (per `/content-podcast` Step 0). |
| `--mode` | no | `single` | `single` (one narrator) or `dialogue` (host + co-host, two voices). Forwarded to `/content-podcast`. |
| `--engine` | no | auto-detected | `kokoro`, `chatterbox`, `vieneu`, or `omnivoice`. Forwarded to `/content-podcast`; see its Step 0 auto-detection rules. |
| `--voice-name` | no | engine default | Preset voice (Kokoro/VieNeu). Forwarded to `/content-podcast`. |
| `--voice` | no | bundled narrator | Voice-clone clip path (Chatterbox/OmniVoice). Forwarded to `/content-podcast`. |
| `--show` | no | inferred | Show name spoken in the welcome. Forwarded to `/content-podcast`. |
| `--out` | no | `podcasts/<slug>--<locale>.mp3` | Output mp3 path. Forwarded to `/content-podcast`. |

Posting always runs with `--backend spotify-cowork` (its human
confirm-before-publish gate stays intact — this command never auto-publishes).

## Pre-conditions

1. The draft must already have passed `/content-review` and `/content-seo` —
   this command runs neither. It checks for `review-reports/<slug>.md`
   (`ship`/`ship-after-fix` disposition) and a passing `seo-reports/<slug>.md`
   before rendering anything.
2. `PODCAST_URL` and `PODCAST_TOKEN` must be set (render server).
3. `requests` must be importable (`pip install requests` if not).
4. A browser-capable runtime for the posting step (Spotify for Creators via
   browser automation).

If any pre-condition fails, the skill's Step 0 preflight stops before
rendering anything and prints the exact fix.

## What it does

Invokes the `content-podcast-all` skill, which:

1. **Preflight** (Step 0) — env vars, `requests`, EN/VI locale gate,
   review+SEO precondition. Fails fast with no artifacts written on any miss.
2. **Render** (Step 1) — `/content-podcast <draft> [flags]`.
3. **Review** (Step 2) — `/content-podcast-review <slug>--<locale>`. **Hard-gates** on
   the verdict: `ship` → continue; `fix`/`regenerate` → stop, do not post,
   report the review-report path.
4. **Post** (Step 3, only on `ship`) — `/content-podcast-posting <slug>--<locale>
   --backend spotify-cowork`, preserving its human confirm-before-publish
   gate.
5. **Stop** (Step 4) — reports the episode URL and tells the user
   `/content-publish` will auto-embed the podcast block; does not run the
   blog spine or `/content-publish` itself.

## What it does NOT do

- Does not write, brief, review, or SEO-audit the blog post — that's the
  blog spine (`/content-idea` → ... → `/content-seo`), or `/content-pipeline`
  end-to-end.
- Does not skip or auto-resolve a non-`ship` review verdict.
- Does not bypass the Spotify posting confirm gate.
- Does not call `/content-publish` — that remains a separate, explicit step.

## Related

- `/content-podcast` — render stage this command sequences.
- `/content-podcast-review` — review gate this command hard-gates on.
- `/content-podcast-posting` — posting stage this command sequences.
- `/content-pipeline` — the full blog spine; use `--podcast` there for a
  combined "topic to published post + podcast" unattended-except-podcast run.
- `/content-publish` — run separately afterward to inject the podcast embed
  and publish the post.
