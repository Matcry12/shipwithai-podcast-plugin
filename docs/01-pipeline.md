# 31 — Content Podcast Pipeline

> Turn any reviewed EN or VI blog post into a spoken companion episode — rendered, reviewed, posted, and auto-embedded in the published article.

---

## What it is

The podcast pipeline converts a reviewed and SEO-audited EN **or VI** draft into a `.mp3` episode via a remote render server (Kokoro, Chatterbox, VieNeu, or OmniVoice TTS, auto-detected per locale). It renders **single narrator** by default, or **host + co-host dialogue** with `--mode dialogue`. It is a **companion** to the article — not a read-aloud — that carries the genuinely valuable ideas in a form that works with eyes closed.

The pipeline has a **locale gate**: the draft's filename suffix (`--en`/`--vi`) and `locale:` frontmatter must agree, or it's refused at Step 0. Both EN and VI are supported. Publishing requires a human confirmation step — auto-publish is never allowed.

---

## Prerequisites

### Environment variables (`.env` — never commit, only `.env.example` is tracked)

| Var | Purpose |
|---|---|
| `PODCAST_URL` | The ngrok HTTPS URL of the render server (printed by `start.command` on the Mac). |
| `PODCAST_TOKEN` | The bearer token printed by `start.command`. |

These are required for `/content-podcast` (the render step). The review step needs no env vars. The posting step (`--backend r2` only) needs additional `PODCAST_R2_*` vars — see below.

### Render server — connecting from other machines

The render server runs on Linh's Mac. Other machines (Linux dev box, CI, another laptop) connect to it over the network via the ngrok tunnel.

**Starting the server (on the Mac):**

```bash
# Double-click setup.command OR run in terminal:
cd /path/to/podcast-generator && ./setup.command
```

`setup.command` prints the ngrok URL and PODCAST_TOKEN on startup. Share both with whoever needs to render.

**Setting up `.env` on another machine:**

```dotenv
PODCAST_URL=https://xxxx-xxx-xxx.ngrok-free.app   # printed by setup.command
PODCAST_TOKEN=<token printed by setup.command>
```

Drop this in `.env` at the root of `shipwithai-content-agent-plugin` (gitignored). Never commit `.env`.

**Verifying the connection:**

```bash
python3 scripts/call_remote.py health
# → {"status": "ok", "device": "mps", ...}
```

**Important: ngrok URL changes on every restart.** If `setup.command` is restarted on the Mac, a new ngrok URL is printed — update `PODCAST_URL` in `.env` on all other machines. The token (`PODCAST_TOKEN`) does not change between restarts.

**On LAN (same WiFi/network):** You can bypass ngrok by using the Mac's local IP instead:

```dotenv
PODCAST_URL=http://192.168.x.x:8000   # Mac's LAN IP, no auth by default on LAN
```

Find the Mac's IP in System Preferences → Network, or `ipconfig getifaddr en0`.

### Pre-pipeline conditions

1. The draft must have passed `/content-review` (score >= ship threshold).
2. The draft must have passed `/content-seo` (AI Citation >= 10/15, AI Detection <= MEDIUM).
3. The draft must be EN or VI: `--en`/`--vi` filename suffix AND matching `locale: en`/`locale: vi` frontmatter.

---

## Where the podcast fits in the full content pipeline

```
/content-idea
  → /content-brief
    → /content-write
      → /content-review         ← must PASS before podcast
        → /content-seo          ← must PASS before podcast
          → /content-podcast    ← render step (NEW)
            → /content-podcast-review   ← quality gate (NEW)
              → /content-podcast-posting  ← publish to platform (NEW)
                → /content-publish  ← auto-embeds the podcast block
```

The podcast is **optional** — skip it entirely if you only want the text post. Run `/content-publish` directly after `/content-seo` for text-only.

---

## Step-by-step walkthrough

### 1. Render the episode

```bash
/content-podcast drafts/<slug>--en.md
/content-podcast drafts/<slug>--vi.md
```

Optional flags:

```bash
/content-podcast drafts/<slug>--en.md --engine kokoro --voice-name af_heart
/content-podcast drafts/<slug>--en.md --engine chatterbox --voice clip.wav
/content-podcast drafts/<slug>--en.md --show "Ship With A.I."
/content-podcast drafts/<slug>--en.md --mode dialogue
/content-podcast drafts/<slug>--vi.md --mode dialogue
```

Engine is auto-detected per locale: EN defaults to `kokoro` (fast preset voices, or `omnivoice` if a cloned voice is configured); `chatterbox` supports voice cloning as an explicit choice. VI has no silent fallback — it defaults to `omnivoice` (or explicit `vieneu`) and stops if the required clip/ref-text env vars aren't set.

**Dialogue mode (`--mode dialogue`):** renders a 2-speaker episode — host
(explains) + curious co-host (asks, pushes back, recaps). The server renders one
voice per request, so `scripts/render_dialogue.py` groups contiguous
same-speaker turns, renders each group with its voice, and concatenates with
ffmpeg. EN uses kokoro `af_heart` (host) + `am_adam` (co-host); VI uses
omnivoice with two reference clips — `PODCAST_VI_VOICE`/`PODCAST_VI_REF_TEXT`
(host) and `PODCAST_VI_VOICE_2`/`PODCAST_VI_REF_TEXT_2` (co-host). Default
remains `single`.

**Output** (all under `podcasts/`, gitignored):

| File | Contents |
|---|---|
| `podcasts/<slug>--<locale>.json` | Render script in PRD shape |
| `podcasts/<slug>--<locale>.mp3` | Rendered episode |
| `podcasts/<slug>--<locale>.transcript.json` | Whisper QA result |
| `podcasts/<slug>--<locale>.podcast.json` | Metadata stub (filled in by posting step) |

### 2. Review the episode

```bash
/content-podcast-review <slug>--<locale>
# or equivalently:
/content-podcast-review podcasts/<slug>--<locale>.json
```

Dispatches the independent `podcast-critic` agent against a 30-pt audio rubric:

| Dimension | Pts |
|---|---|
| Faithfulness | 8 |
| Value | 6 |
| Eyes-free sayability | 6 |
| Standalone | 3 |
| Memorability (≤3 key points, repeated takeaway, concrete anchors, recap) | 5 |
| Render integrity (Whisper overlap >= 85%) | 2 |

**Verdict options:**

- `ship` — score >= 24/30, no faithfulness failure → proceed to posting.
- `fix` — minor sayability/standalone issues only → edit `podcasts/<slug>--<locale>.json`, re-render, re-review.
- `regenerate` — invented claim or substantive faithfulness/value miss → re-author from scratch.

A faithfulness failure is a hard fail regardless of total score. The loop is bounded: after 2 fix/regenerate cycles the third failure is surfaced to the human rather than looped again.

**Output:** `podcast-reports/<slug>--<locale>.md` (gitignored).

### 3. Post the episode

```bash
/content-podcast-posting <slug>--<locale>
# or with explicit backend:
/content-podcast-posting <slug>--<locale> --backend spotify-cowork
/content-podcast-posting <slug>--<locale> --backend r2
```

**`spotify-cowork` (default):** uploads the `.mp3` to Spotify for Creators via browser automation. No env vars required — uses your existing browser session. **The skill pauses for human confirmation before clicking Publish.** Requires a desktop or remote-display environment (fails in headless CI).

**`r2`:** uploads directly to Cloudflare R2. Fully automated once credentials are set; requires five `PODCAST_R2_*` env vars:

| Var | Purpose |
|---|---|
| `PODCAST_R2_ACCOUNT_ID` | Cloudflare account ID |
| `PODCAST_R2_ACCESS_KEY` | R2 API token Access Key ID |
| `PODCAST_R2_SECRET_KEY` | R2 API token Secret Access Key |
| `PODCAST_R2_BUCKET` | R2 bucket name |
| `PODCAST_R2_PUBLIC_BASE` | Public base URL (e.g. `https://assets.example.com`) |

After posting, `podcasts/<slug>--<locale>.podcast.json` is updated with `{type, url, embedUrl, episodeId}`.

### 4. Publish the post (auto-embeds the podcast)

```bash
/content-publish drafts/<slug>--en.md
```

`/content-publish` reads `podcasts/<slug>--<locale>.podcast.json` and automatically injects the podcast embed block into the published post frontmatter. No extra step needed — the embed is wired in.

On the website, the `podcast` frontmatter block renders as:
- **Spotify episode** → embed iframe (PodcastPlayer component).
- **R2 audio URL** → HTML5 `<audio>` player.

---

## Command reference table

| Command | Purpose | Backend / flags |
|---|---|---|
| `/content-podcast <draft--en.md>` | Render `.mp3` via remote server | `--mode single\|dialogue`, `--engine kokoro\|chatterbox`, `--voice-name`, `--voice`, `--show` |
| `/content-podcast-review <slug>--<locale>` | Independent quality gate (podcast-critic, 30 pts) | — |
| `/content-podcast-posting <slug>--<locale>` | Upload + write metadata stub | `--backend spotify-cowork` (default) or `--backend r2` |
| `/content-publish <draft>` | Publish post; **auto-embeds** podcast block | standard publish flags |

---

## Rules

- **Locale gate.** `/content-podcast` accepts EN or VI drafts, but the filename suffix (`--en`/`--vi`) and `locale:` frontmatter must agree at Step 0 — a mismatch, or any other locale, is refused with no artifacts written. There is no override.
- **Confirm before publish.** The `spotify-cowork` backend always stops for human confirmation. Never auto-publish.
- **Review must ship.** `/content-podcast-posting` should only run after `/content-podcast-review` returns `ship`. A faithfulness failure is a hard block.
- **Env vars in `.env` only.** Never hardcode `PODCAST_URL`, `PODCAST_TOKEN`, or any `PODCAST_R2_*` value. Only `.env.example` is committed to the repo.

---

## See also

- `commands/content-podcast.md` — full argument reference for the render step.
- `commands/content-podcast-review.md` — scoring rubric detail and bounded loop rules.
- `commands/content-podcast-posting.md` — backend detail and R2 env var table.
- `skills/content-podcast/SKILL.md` — the step-by-step skill procedure.
- `docs/11-publish-path.md` — overall publish path context.
- `docs/29-command-playbook.md` — the full command playbook including podcast commands.
