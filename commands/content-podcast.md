---
name: content-podcast
description: Turn a reviewed+seo'd EN or VI draft into a podcast .mp3 via the remote render server (Kokoro, Chatterbox, VieNeu, or OmniVoice) — single narrator by default, or host+co-host dialogue with `--mode dialogue` — a spoken companion, not a read-aloud — with an integrated value/faithfulness/sayability self-check and Whisper QA.
argument-hint: drafts/<slug>--en.md|--vi.md [--mode single|dialogue] [--engine kokoro|chatterbox|vieneu|omnivoice] [--voice-name af_heart | --voice clip.wav] [--show "Name"] [--out podcasts/<slug>.mp3]
---

# /content-podcast

Turn a reviewed and seo'd EN or VI draft into a podcast episode — single
narrator by default, or host+co-host dialogue with `--mode dialogue`.
Delegates the full procedure to the `content-podcast` skill.

## Usage

```
/content-podcast drafts/<slug>--en.md
/content-podcast drafts/<slug>--vi.md
/content-podcast drafts/<slug>--en.md --engine kokoro --voice-name af_heart
/content-podcast drafts/<slug>--en.md --engine chatterbox --voice clip.wav
/content-podcast drafts/<slug>--en.md --show "Ship With A.I."
/content-podcast drafts/<slug>--en.md --mode dialogue
/content-podcast drafts/<slug>--vi.md --mode dialogue
```

## Arguments

| Arg | Required | Default | Meaning |
|---|---|---|---|
| `drafts/<slug>--en.md` or `drafts/<slug>--vi.md` (first positional) | yes | — | Path to the reviewed+seo'd draft. Locale is auto-detected from the `--en`/`--vi` suffix; must agree with `locale:` frontmatter. |
| `--mode` | no | `single` | `single` (one narrator) or `dialogue` (host + curious co-host, two voices). Dialogue supports EN `kokoro` and VI `omnivoice` only. |
| `--engine` | no | auto-detected | EN: `omnivoice` if configured, else `kokoro` (fallback), or `chatterbox`. VI: `omnivoice` only (or explicit `vieneu`) — no silent fallback. |
| `--voice-name` | no | `af_heart` (EN) / `Ngọc Lan` (VI) | **Kokoro/VieNeu only** — preset voice (`af_heart`, `af_sarah`, `am_adam`, …; VieNeu: `Ngọc Lan`, `Đức Trí`, …). |
| `--voice` | no | bundled narrator | **Chatterbox/OmniVoice only** — path to a 6–10 s mono `.wav` to clone. |
| `--show` | no | inferred | Show name spoken in the welcome (e.g. `"Ship With A.I."`). Always spell it sayably. |
| `--out` | no | `podcasts/<slug>.mp3` | Output mp3 path. Must be under `podcasts/`. |

## Required env vars

| Var | Purpose |
|---|---|
| `PODCAST_URL` | The ngrok https URL of the render server (printed by `start.command` on the Mac). |
| `PODCAST_TOKEN` | The bearer token printed by `start.command`. |

If either is unset, the skill stops and asks the user to provide them. Never hardcode.

## Pre-conditions

1. The draft must have passed `/content-review` and `/content-seo`.
2. The draft must be EN or VI: filename suffix (`--en`/`--vi`) AND `locale:` frontmatter must agree. A mismatch, or a suffix that's neither, is refused at Step 0 with no artifacts written.
3. `scripts/call_remote.py` requires `requests` (`pip install requests`).

## What it does

Invokes the `content-podcast` skill, which:

1. Detects locale (EN or VI) from filename suffix + frontmatter, and auto-detects the render engine (Step 0).
2. Reads the draft, derives `<slug>`.
3. Triages to genuinely valuable ideas; rewrites for the ear (companion, not transcript).
4. Makes every token sayable (acronyms, identifiers, numbers, paths → spoken words).
5. Enforces chunker rules (capitalized lines, terminal punctuation, balanced quotes).
6. Self-checks value / eyes-free / faithfulness / standalone (max 2 revision passes).
7. Emits `podcasts/<slug>.json` (render script in PRD shape).
8. Renders via `${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py` (single mode) or `scripts/render_dialogue.py` (`--mode dialogue`), using the auto-detected or requested engine/voice.
9. Runs Whisper QA → `podcasts/<slug>.transcript.json`; reports overlap %.
10. Emits the metadata stub `podcasts/<slug>.podcast.json`.
11. Reports engine, voice, mp3 path + size, QA verdict, and artifact paths.

## Output artifacts

All written under `podcasts/` (gitignored):

| File | Contents |
|---|---|
| `podcasts/<slug>.json` | Render script (PRD shape). |
| `podcasts/<slug>.mp3` | Rendered episode. |
| `podcasts/<slug>.transcript.json` | Whisper QA result with `overlapPct`. |
| `podcasts/<slug>.podcast.json` | Metadata stub; `podcast` block (`{type, url, embedUrl, episodeId}`) empty until `/content-podcast-posting` fills it. |

## After this command

Run `/content-podcast-review <slug>` for the independent quality gate before
proceeding to `/content-podcast-posting`.

## Related

- `/content-review` — must pass before running this.
- `/content-seo` — must pass before running this.
- `/content-podcast-review` — independent review gate (run after this).
- `/content-podcast-posting` — publishes the episode (default `--backend spotify-cowork`, or `--backend r2`); run after review passes.
- `/content-publish` — final publish step (Step 2.5 injects the `podcast` block into the post frontmatter so the site renders the player).
