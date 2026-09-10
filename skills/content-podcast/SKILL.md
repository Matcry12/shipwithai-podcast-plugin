---
name: content-podcast
description: Full step-by-step procedure to turn a reviewed+seo'd EN or VI draft into a podcast .mp3 (single narrator or 2-speaker dialogue) via the remote render server, with integrated value/faithfulness/sayability/memorability self-check, Whisper QA, and metadata stub emission.
---

# content-podcast

Convert a reviewed+seo'd EN **or VI** draft into a podcast episode (single narrator, or host + co-host dialogue with `--mode dialogue`) that is
**worth a listener's time** — a spoken *companion* to the article, not a read-aloud
of it. You (the assistant) decide what's genuinely valuable, rewrite it for the
**ear**, self-check, then call the **remote render server** to produce the `.mp3`
and run QA.

## The bar (read this first — it governs every step)

The listener has NOT read the article and is doing something else (commuting,
dishes). It must make sense **with eyes closed**. Optimize for **value, not
length** — never stretch to fill time, never amputate to hit a target. The right
length is "just enough": carry the ideas worth hearing, drop everything else.

- **Companion, not transcript.** Convey the article's genuinely valuable ideas
  conceptually. Skip setup boilerplate, ceremony, and copy-paste detail — that
  lives on the page; point the listener there once for it.
- **Translate, don't transcribe.** Turn technical specifics into their concept
  ("a CI job that re-runs on every push"), not the raw syntax. Never read code,
  config, flags, or identifiers aloud.
- **Teach order, not article order.** Sequence ideas the way they actually land
  for a listener — lead with the payoff/why, not the article's preamble.
- **Natural spoken delivery.** Contractions, connective tissue ("and the thing
  is…", "so what actually happens is…"). Warm, concrete, a little wry. No hype,
  no filler.

The render models (Chatterbox / Kokoro / Whisper) live on a remote Mac reached
over an ngrok tunnel. This skill never loads a model locally — it only writes
`script.json` and drives `call_remote.py`.

---

## Inputs

Parse from `$ARGUMENTS`:

| Arg | Required | Default | Meaning |
|---|---|---|---|
| `drafts/<slug>--en.md` or `drafts/<slug>--vi.md` (first positional) | yes | — | Path to the reviewed+seo'd draft. Locale is auto-detected from the `--en` / `--vi` suffix. |
| `--mode` | no | `single` | `single` (one narrator) or `dialogue` (host + curious co-host, two voices). Dialogue supports EN `kokoro` and VI `omnivoice` only. |
| `--engine` | no | auto-detected (see Step 0) | EN: `omnivoice` if configured, else `kokoro` (fallback), or `chatterbox`. VI: `omnivoice` only — no fallback engine. |
| `--voice-name` | no | `af_heart` (EN) / `Ngọc Lan` (VI) | **Kokoro / VieNeu** — preset voice. Kokoro: `af_heart`, `af_sarah`, `am_adam`, … VieNeu: `Ngọc Lan`, `Đức Trí`, `Mỹ Duyên`, `Thái Sơn`, `Trúc Ly`, … |
| `--voice` | no | bundled narrator | **Chatterbox / OmniVoice** — path to a 6–10 s mono `.wav` to clone. For OmniVoice, also set `$PODCAST_VI_VOICE` as a fallback. |
| `--show` | no | inferred | Show name spoken in the welcome (e.g. `"Ship With A.I."`). If omitted, infer from the article's source; if none is clear, use a plain welcome without a brand. Always spell it sayably — write the `AI` in the brand as `A.I.` (dotted, no spaces), the form calibrated clearest for kokoro `af_heart` (see Step 3). |
| `--out` | no | `podcasts/<slug>--<locale>.mp3` | Output mp3 path. |
| `--local` | no | off | Render with the **local** Kokoro ONNX model instead of the remote server (see Step 7). **EN only**; single narrator and dialogue both work. No `PODCAST_URL`/`PODCAST_TOKEN` needed. Whisper QA still runs, locally (Step 8). Use for demos and fast iteration where flow matters more than final quality. |

**Engine ↔ voice rule (enforce this):**
- `--engine kokoro` → use `--voice-name`; **ignore** `--voice` (Kokoro cannot clone a clip).
- `--engine chatterbox` → use `--voice` if given, else the server's bundled narrator; **ignore** `--voice-name`.
- `--engine vieneu` → use `--voice-name` (e.g. `Ngọc Lan`); **ignore** `--voice`.
- `--engine omnivoice` → use `--voice` clip if given, else reads `$PODCAST_VI_VOICE`, else bundled narrator; **ignore** `--voice-name`.
- If the user passes the wrong voice flag for the engine, warn and fall back to the engine's default rather than failing.

**Server connection** comes from the environment (the caller sets these once):
- `PODCAST_URL` — the ngrok https URL of the render server.
- `PODCAST_TOKEN` — the bearer token printed by `start.command`.
- `PODCAST_VI_VOICE` — (VI only) absolute path to a 6–10s mono `.wav` reference clip for OmniVoice voice cloning. Record your own clip and set this to its path on each machine. Optional — if unset, the server's bundled narrator is used.
- `PODCAST_VI_REF_TEXT` — (VI OmniVoice only) transcription of `PODCAST_VI_VOICE` clip. Supplying it skips the per-turn Whisper pass on the server and cuts render time from ~20 min to ~5 min for a 14-turn script.

If `PODCAST_URL` or `PODCAST_TOKEN` is missing, **STOP** and ask the user for the URL + token from the Mac host. Never hardcode them.

**VI voice quality warning (omnivoice only):** If `PODCAST_VI_VOICE` or `PODCAST_VI_REF_TEXT` is unset when `--engine omnivoice` is used, the server picks a random voice each turn — the podcast will sound like a different person every sentence. **STOP before rendering** and tell the user:

> "PODCAST_VI_VOICE and PODCAST_VI_REF_TEXT are not set. Without these, OmniVoice will use a different random voice each turn. Please add them to .env (see .env.example for the template) and re-run."

Do not proceed with the render if either is unset for an omnivoice VI job.

**Dialogue guard (`--mode dialogue` + omnivoice):** dialogue clones TWO voices,
so BOTH speakers need their own reference clip + transcript in `.env`, for the
locale being rendered:
- EN: `PODCAST_EN_VOICE`/`PODCAST_EN_REF_TEXT` (host) + `PODCAST_EN_VOICE_2`/`PODCAST_EN_REF_TEXT_2` (co-host).
- VI: `PODCAST_VI_VOICE`/`PODCAST_VI_REF_TEXT` (host) + `PODCAST_VI_VOICE_2`/`PODCAST_VI_REF_TEXT_2` (co-host).

If any of the four for that locale is unset, **STOP before rendering** and ask
the user to add them to `.env` (see `.env.example`). Without a co-host clip the
second speaker falls back to the default voice, so the two speakers won't be
distinct. (EN dialogue via `--engine kokoro` uses presets and needs no clips —
this guard is for the omnivoice cloning path only.)

**Runtime dependency:** `scripts/call_remote.py` requires the `requests` package.
If not installed, instruct: `pip install requests`.

---

## Step 0 — Locale detection

Before any other work, detect the locale from the draft filename and frontmatter:

1. Check the filename suffix: `--en.md` → `locale=en`, `--vi.md` → `locale=vi`.
2. Read the frontmatter and confirm `locale:` agrees.

Both must agree. If they conflict, or if the suffix is neither `--en` nor `--vi`, **STOP** and ask the user to clarify.

**Engine auto-detection (unless `--engine` is explicitly passed):** check whether
OmniVoice is configured for the locale/mode being rendered — the relevant env vars
from `.env` are set (single mode: `PODCAST_<LOCALE>_VOICE`; dialogue mode: also
`PODCAST_<LOCALE>_VOICE_2`) — and that the render server's `/health` reports
`omnivoice` present (not missing).

- `locale=en`:
  - OmniVoice configured → default engine `omnivoice` (consistent cloned voice).
  - Not configured → **fallback** default engine `kokoro`, default voice-name `af_heart`.
- `locale=vi`:
  - OmniVoice is the only default — VI has **no fallback engine**. If
    `PODCAST_VI_VOICE`/`PODCAST_VI_REF_TEXT` (and, in dialogue mode, the `_2`
    pair) are unset, follow the VI voice quality warning above: **STOP** and ask
    the user to set them rather than silently falling back to `vieneu`.
    `vieneu` remains available only via an explicit `--engine vieneu`.

Carry `locale` and `engine` through all subsequent steps.

---

## Step 1 — Read the draft

Read the draft file. Derive `<slug>` from the filename stem (strip directories, strip `--en.md` or `--vi.md`). If `--out` was not given, set it to `podcasts/<slug>--<locale>.mp3`.

---

## Step 2 — Find the value, then write for the ear

First, **triage**: read the whole article and decide what's genuinely worth
hearing — the ideas, the "why", the one or two things that change how the
listener works. Discard the rest (boilerplate intros, exhaustive option lists,
copy-paste blocks). Let the count of ideas — not a word target — decide the
length.

**Memorability rules (both modes — this is what makes the episode stick).**
Audio retention is far lower than reading; an episode that accurately covers
everything is an episode where nothing is remembered. Enforce:

- **Max 3 key points.** If the article has more, pick the 3 that most change
  how the listener works, and name the cut once ("the post covers a few more —
  they're all there when you want them").
- **One core takeaway sentence**, stated three times: in the hook, at the
  midpoint, and in the close. Same idea, natural rewording each time.
- **Every key point gets a concrete anchor** — an example, story, number, or
  analogy from the article. No abstract-only points; abstractions are what
  listeners forget first.
- **Signpost transitions**: "that's the first thing — the second is…" so a
  distracted listener always knows where they are.
- **Closing recap**: restate the 3 points in one breath, then one thing to try
  today. In dialogue mode the co-host does the recap.

**Dialogue mode (`--mode dialogue`) — host + curious co-host.** Two voices only
pay off through role contrast, not timbre contrast. Write two distinct people:

- **Both speakers know the material and both explain it.** The co-host is a
  second informed person, not the listener's proxy — they contribute specific
  facts, examples, and comparisons from the article, not just questions and
  reactions. A co-host who only asks and never explains reads as an audience
  member, not a co-host; that is a defect, not a style choice.
- **Word count check.** Sum each speaker's words across the script. If either
  speaker is carrying much more than the other (rough guide: past a 60/40
  split), rebalance — move a substantive point to the lighter speaker's turn
  instead of padding it with filler. Neither speaker should dominate the episode.
- The co-host still asks the question a listener would ask ("wait, why not
  just…?"), pushes back **once per key point**, and recaps each section in
  their own words — but that is only part of their role, not all of it. They
  also take turns building out a point, adding an example the article gives,
  or explaining a sub-topic while the host reacts/asks — the same moves the
  host makes.
- Turns alternate naturally but not mechanically — either speaker may take 2–3
  turns to build a point; the other interjects where a real person would.
- A co-host turn that could be reassigned to the host without anyone noticing
  is fine **as long as it carries real content** (a fact, example, or specific
  claim) — what's banned is a co-host turn with no content at all: pure
  reaction/filler that says nothing a listener couldn't already infer.
- **Turns must connect — this is the difference between a conversation and two
  monologues.** Every turn after the opening reacts to the *specific words* of the
  turn right before it: answer the exact question asked, pick up a phrase the
  other person just used, or challenge the precise claim just made. Test each
  turn against the one before it: if it would read the same with the previous
  turn deleted, it is a monologue chunk, not dialogue — rewrite it so it hooks
  into what was actually just said.
- **Answer before you advance.** When the co-host asks something, the host's next
  turn addresses that question first, in plain words, before moving to the next
  point. No "great question — anyway, moving on".
- **Ban fake-interest filler.** Co-host lines like "interesting, tell me more" or
  "wow, that's wild" with no specific content are placeholders, not conversation.
  Every co-host turn must name the specific thing it is reacting to.
- **Carry threads forward.** Use callbacks — "back to your point about X", "like
  you said earlier" — so the episode plays as one continuous conversation, not a
  list of alternating statements.
- VI dialogue: same roles in natural VN dev register; all VI rules below
  (bare English terms, numbers in words) apply to both voices.

**Open natural — hook first, THEN welcome (do not skip this).** The very first
turns are:

1. **Cold-open hook** (1–2 turns) — open on the single most surprising or
   highest-stakes point. NO greeting yet; make a stranger lean in.
2. **Bridge into the welcome + names** (1–2 turns) — connect *from* the hook into
   the welcome, don't reset. Start with a connector that ties back ("And if that
   sounds familiar…", "If any of that hits close to home…"), then welcome the
   listener and, **in dialogue mode, have both speakers introduce themselves by
   name once** — natural and quick, not a roll call. Then say, in plain words,
   what this episode is about. Warm, brief.
   - **Dialogue, with `--show`:** host — *"And if that sounds familiar, welcome to Ship With A.I. I'm Adam."* → co-host — *"and I'm Anna — today we're getting into how to make your A.I. pull-request reviews run while you sleep."*
   - **Dialogue, no show name:** host — *"And if that sounds familiar, you're in the right place. I'm Adam,"* → co-host — *"and I'm Anna. Let's get into it."*
   - **Single narrator:** no self-introduction — just the plain welcome as before.
   - **Names:** use `$PODCAST_HOST_NAME` / `$PODCAST_COHOST_NAME` if set; otherwise default to **Adam** (host) and **Anna** (co-host). For VI, pick natural Vietnamese names if the env names are unset (e.g. Minh / Linh). Introduce each name exactly once; never re-announce names later.
3. Then flow into the body below.

Never drop a flat "Welcome to the show" with no connection to the hook, and never
read the show name in an un-sayable form. Close with a warm sign-off and one thing
to try.

**VI drafts (`locale=vi`):** Write the companion script entirely in Vietnamese. Apply the same companion principles — hook first, value over length, ear not eye — but in natural spoken Vietnamese:
- Use informal dev-to-dev register (same tone as the article's `vi.md` locale voice).
- Contractions and connectors in Vietnamese: "Và điều thú vị là…", "Nên trước khi nói về…", "Vậy thực ra chuyện gì xảy ra là…"
- Avoid English jargon where a natural Vietnamese equivalent exists; keep technical terms (API, token, commit) as-is since they are standard in VI dev speech.
- Numbers in words: `50%` → "năm mươi phần trăm", `2026` → "hai nghìn không trăm hai mươi sáu".
- Never mix languages mid-sentence unless the article itself does.
- **English tech terms for VI TTS — leave them bare, do NOT phonetically Vietnamize.** omnivoice pronounces English words (Agent, Tool, Loop, deploy, commit, GitHub, Claude Code) acceptably inside Vietnamese sentences, and that reads as natural dev code-switching. Forced syllabic respelling (Agent → "Ây Dần", GitHub → "Gít Hắp") sounded *worse* in an A/B ear-test (owner, 2026-07-01) — write the English word as-is. The only exception is bare initialisms, which still need the Step 3 dotted-letter treatment: `API` → "A.P.I.".

Then rewrite the kept ideas into natural single-narrator narration, one `turn` per
developed thought (mix longer breathing turns that build a point with short ones):

- **Headings** → spoken transitions ("So here's where it gets interesting…"),
  never read verbatim.
- **Links / URLs** → plain words; **never read a URL aloud**.
- **Code / config / commands** → the *concept* of what it does, never the
  syntax. "A small script that fails the build if coverage drops" — not the
  script.
- **Images / diagrams / tables** → convey the takeaway in words, or skip; never
  say "as shown below" or "see the diagram".
- **Signpost once** — at least once, point to the article for the copy-paste
  detail ("the full config's in the post if you want to lift it"). Audio =
  understanding; page = detail.

---

## Step 3 — Make every token sayable (eyes-free rules — this is what makes or breaks it)

The TTS reads literally. A raw identifier gets mangled ("T0" → "tee-zero",
"DATABASE_URL" → "database underscore U R L"). Convert **every** un-sayable
token to spoken words BEFORE emitting:

- **Acronyms** → dotted letters: `AI` → "A.I.", `MCP` → "M.C.P.", `API` → "A.P.I.", `OpenAPI` → "open A.P.I.". The dotted form (periods, no spaces) is calibrated clearest for kokoro `af_heart` — the periods make the engine insert micro-pauses so the letters stay distinct instead of slurring into the surrounding words (owner ear-test, 2026-06-17; ranked best of: `A.I.` > `A - I` > wrapping in "the … show" > comma-isolated `A, eye`). Spaced letters ("M C P") are an acceptable fallback but read less cleanly.
- **Identifiers / job names / codes** → the concept: `T0/T1/T3` → "the first job… the third job"; `STRIPE_SECRET_KEY` → "the Stripe secret key".
- **Numbers, %, versions, years** → words: `50%` → "about fifty percent", `2026` → "twenty twenty-six", `v1.2` → "version one point two", `204` → "a two-oh-four".
- **camelCase / dotted names** → spell or conceptualize: `settings.json` → "the settings file", `TypeORM` → "Type O R M".
- **All-caps product/brand names** → normal case: write CLAUDE as "Claude", GITHUB as "GitHub", OPENAI as "OpenAI". Kokoro reads all-caps tokens as shouted or garbled strings (e.g. CLAUDE was heard as "Claw M D"); never leave a product or brand name in all-caps.
- **Filenames / paths / flags** → spoken form: `CLAUDE.md` → "the Claude dot M D file", `--strict` → "the strict flag".
- **Mid-sentence hyphenated compounds** → prefer an un-hyphenated phrasing. Observed: kokoro `af_heart` clipped the tail of a sentence ending in a hyphenated compound (`fact-checking pass caught it` → audio dropped "checking pass caught it") **even at 99%+ Whisper overlap** — the localized drop did not show up in the overlap score, only in the independent critic's segment inspection. Rewrite "a fact-checking pass" as "a review pass whose job was checking facts", "real-time" as "live", etc. (owner observation, 2026-06-18).
- When in doubt, **prefer the concept over the exact token.** If a word is genuinely hard to pronounce (e.g. "idempotent") and not essential, say its plain meaning instead ("a bot you can safely run twice").

---

## Step 4 — Obey the renderer's chunker rules (hard requirement)

Every `line` MUST satisfy ALL of these or the render aborts:
- Starts with a capital letter.
- Ends with terminal punctuation: `.` `!` `?` (a closing quote after it is fine).
- No leading punctuation.
- Balanced quotes (opened and closed within the same line).

Fix any line that violates these before emitting.

---

## Step 5 — Self-check (integrated evaluation, max 2 revision passes)

Before emitting, review your own draft against the article AND the bar above:
- **Value** — would a listener finish this feeling it was worth their time? Is
  anything here padding or boilerplate that should be cut? Is anything genuinely
  valuable missing?
- **Eyes-free** — does it make sense with eyes closed? Read every line as if
  hearing it: any surviving raw token, acronym, code, or number-as-digit? (Step 3) Fix them.
- **Faithfulness** — every claim supported by the article; nothing invented (no
  made-up numbers, no invented outcomes).
- **Standalone** — no "as shown below" / "the diagram" / bare-URL / "read this
  code" references that only make sense on the page.

If any check fails, revise (bounded: at most 2 passes), then proceed. This is a
self-review inside this one skill — by design, not a separate grader. The
independent gate is `/content-podcast-review`.

---

## Step 6 — Emit `podcasts/<slug>--<locale>.json` (PRD shape)

Write `podcasts/<slug>--<locale>.json`:

```json
{
  "host_mode": "single",
  "voice": "narrator",
  "turns": [
    { "voice": "narrator", "line": "First spoken segment." },
    { "voice": "narrator", "line": "Second spoken segment." }
  ]
}
```

**Dialogue mode** instead emits:

```json
{
  "host_mode": "dialogue",
  "turns": [
    { "voice": "host",   "line": "First spoken segment." },
    { "voice": "cohost", "line": "Wait — why does that matter?" }
  ]
}
```

- Single mode: `host_mode: "single"`, every turn `"voice": "narrator"` — the
  engine voice is chosen at render time by the flags, not inside the script.
- Dialogue mode: `host_mode: "dialogue"`, every turn's `voice` is exactly
  `"host"` or `"cohost"`; the two engine voices are chosen at render time.
- `exag` (0.0–1.0) is **Chatterbox-only** expressiveness; you may add it per
  turn for chatterbox renders. Kokoro ignores it harmlessly.

---

## Step 7 — Render

### 7-LOCAL — when `--local` was passed (EN only)

`scripts/call_local.py` is the local counterpart of `call_remote.py`: same
subcommands, same contracts, no server / tunnel / token. Kokoro ONNX runs on
this machine at roughly 2.5x realtime, so a 5-minute episode takes about 2
minutes.

```bash
"${VIDEOMAKER_ROOT:-$HOME/Documents/Video maker}/.venv/bin/python" \
  "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_local.py" render \
  --script podcasts/<slug>--en.json \
  --out    podcasts/<slug>--en.mp3
```

Mode is auto-detected from the script's speakers, exactly like the remote
factory: one speaker renders single-narrator, two renders a dialogue. Voices
default to `af_heart` (US female) for the first speaker and `am_adam` (US male)
for the second; override with `--voice-name` and `--voice-name-2`. Any of the
28 EN presets work (`af_*`/`am_*` US, `bf_*`/`bm_*` British). Three or more
speakers is an error, not a guess.

It must run under that venv — that is where `kokoro_onnx`, `faster_whisper` and
the model files live. If it exits with `no Video-maker checkout`, set
`VIDEOMAKER_ROOT`.

**`--local` is EN-only.** For VI, or for a final-quality render (voice cloning,
the tuned server engines), drop `--local` and use the remote path below.

### 7-REMOTE — the default

`scripts/call_remote.py render` is a factory: pass the script and the output
path, and it derives everything else — single vs. dialogue (from the
script's `host_mode`), locale (from the `--en`/`--vi` filename suffix),
engine (per the Step 0 auto-detection rule), and OmniVoice voice
clips/ref-texts (from `PODCAST_<LOCALE>_VOICE[_2]` / `_REF_TEXT[_2]` in
`.env`). This is the only invocation you need in the normal case, for both
single-narrator and dialogue scripts:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py" render \
  --url   "$PODCAST_URL" \
  --token "$PODCAST_TOKEN" \
  --script podcasts/<slug>--<locale>.json \
  --out    podcasts/<slug>--<locale>.mp3
```

Sanity-check what it resolved before spending a real render, with `--dry-run`
(prints the plan — mode/locale/backend/voices — and exits without touching
the server):

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py" render \
  --script podcasts/<slug>--<locale>.json \
  --out    podcasts/<slug>--<locale>.mp3 \
  --dry-run
```

On success the server returns the mp3 and `call_remote.py` writes
`podcasts/<slug>--<locale>.mp3` plus a size line. Dialogue scripts are routed
internally through `scripts/render_dialogue.py`'s logic (groups contiguous
same-speaker turns, renders each, concatenates with ffmpeg — requires
`ffmpeg` on PATH); still follow the VI voice-quality warning and dialogue
guard in **Inputs** above before rendering.

### Overrides (rarely needed)

Every flag below is optional and, when passed, takes precedence over what
the factory would have derived — use these only to force a specific engine,
locale, clip, or OmniVoice tuning. **Which flags actually apply depends on
the script's mode** (`single` vs `dialogue`, from `host_mode` in the
script.json) — `call_remote.py render` auto-detects mode from the script, not
from a CLI flag, so the same command line can hit either column below
depending on which script.json you point it at:

| Flag | Single-narrator scripts | Dialogue scripts |
|---|---|---|
| `--locale en\|vi` | Forces locale, instead of the `--script`/`--out` `--en`/`--vi` suffix (or script-text detection as a last resort). | Same — applies to both scripts. |
| `--backend chatterbox\|kokoro\|vieneu\|omnivoice\|dummy` | Forces engine, instead of the Step 0 auto-detect rule. | Same — applies to both speakers. |
| `--ov-speed`, `--ov-num-step` | OmniVoice tuning, instead of the server defaults. | Same — applied to both speakers identically. |
| `--voice <clip.wav>` | Forces the Chatterbox/OmniVoice clone clip, instead of `PODCAST_<LOCALE>_VOICE`. | **Ignored** — dialogue always resolves per-speaker clips from `.env` (`PODCAST_<LOCALE>_VOICE`/`_VOICE_2`). `call_remote.py` prints a `NOTE:` to stderr when it sees this flag on a dialogue script. |
| `--voice-name <name>` | Forces the Kokoro/VieNeu preset, instead of the engine default. | **Ignored** for the same reason — a `NOTE:` is printed. (Dialogue's kokoro path does use presets, but fixed `af_heart`/`am_adam`, not this flag.) |
| `--ov-ref-text`, `--ov-guidance-scale`, `--ov-denoise`, `--ov-t-shift`, `--ov-class-temp` | OmniVoice tuning, instead of the server defaults. | **Ignored** — a `NOTE:` is printed. |

```bash
# Force chatterbox with an inline clip on a single-narrator script:
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py" render \
  --url "$PODCAST_URL" --token "$PODCAST_TOKEN" \
  --script podcasts/<slug>--<locale>.json --out podcasts/<slug>--<locale>.mp3 \
  --backend chatterbox --voice <clip.wav>

# Force VieNeu preset instead of OmniVoice cloning:
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py" render \
  --url "$PODCAST_URL" --token "$PODCAST_TOKEN" \
  --script podcasts/<slug>--<locale>.json --out podcasts/<slug>--<locale>.mp3 \
  --backend vieneu --voice-name "Ngọc Lan"
```

For dialogue scripts, `call_remote.py render` only honors `--backend` /
`--ov-speed` / `--ov-num-step` as overrides (applied to both speakers — voice
clips are still resolved per-locale from `.env`); any other flag from the
table above is ignored with a `NOTE:` on stderr, never silently. For
per-speaker control — distinct `--host-voice`/`--cohost-voice` clips, `--gap`,
or `--no-fade` — call `scripts/render_dialogue.py` directly; it remains a
fully working standalone CLI with all of those flags:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/render_dialogue.py" \
  --script podcasts/<slug>--<locale>.json \
  --out    podcasts/<slug>--<locale>.mp3 \
  --backend omnivoice --locale vi --ov-speed 0.85 \
  --host-voice /custom/host.wav --cohost-voice /custom/cohost.wav
```

---

## Step 8 — Whisper QA

Transcribe the result and diff it against the script.

**When `--local` was passed**, run faster-whisper on this machine instead. It
writes the same `{text, segments, overlapPct}` shape, so the `>= 85%` rule
below reads identically:

```bash
"${VIDEOMAKER_ROOT:-$HOME/Documents/Video maker}/.venv/bin/python" \
  "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_local.py" transcribe \
  --mp3    podcasts/<slug>--en.mp3 \
  --script podcasts/<slug>--en.json \
  --out    podcasts/<slug>--en.transcript.json
```

Model size defaults to `base.en`; override with `$LOCAL_WHISPER_SIZE`. It is a
smaller model than the server's, so treat a local `WARN` as "look at it"
rather than proof of a bad render.

Otherwise (remote render):

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/call_remote.py" transcribe \
  --url   "$PODCAST_URL" \
  --token "$PODCAST_TOKEN" \
  --mp3   podcasts/<slug>--<locale>.mp3 \
  --script podcasts/<slug>--<locale>.json \
  --out   podcasts/<slug>--<locale>.transcript.json
```

Read `overlapPct` from the transcript JSON:
- **>= 85%** → report `QA: PASS (NN% overlap)`.
- **< 85%** → report `QA: WARN (NN% overlap)` and list the mismatched segments.
  A low overlap is often a Whisper mistake (homophones, proper nouns), not a bad
  render — flag it for human review, do not silently fail.

---

## Step 9 — Emit the metadata stub

Write `podcasts/<slug>--<locale>.podcast.json`:

```json
{
  "slug": "<slug>",
  "episodeTitle": "<spoken episode title>",
  "sourcePost": "drafts/<...>--en.md or --vi.md",
  "locale": "en or vi",
  "mp3Path": "podcasts/<slug>--<locale>.mp3",
  "engine": "kokoro",
  "mode": "single",
  "voice": "af_heart",
  "qaOverlapPct": 0.0,
  "podcast": {
    "type": "",
    "url": "",
    "embedUrl": "",
    "episodeId": ""
  }
}
```

- `episodeTitle` — the spoken title as it would appear in a podcast app (derive
  from the episode's opening or the draft's title; make it sayable).
- `engine` / `mode` / `voice` — record what was actually used. Dialogue mode:
  `"mode": "dialogue"` and `"voice": "af_heart + am_adam"` (host + cohost).
- `qaOverlapPct` — fill with the `overlapPct` value from the Whisper QA result.
- `podcast` — leave all four fields empty; filled later by `/content-podcast-posting`
  (`type` becomes `audio` for R2/GitHub direct-mp3, or `spotify` for the cowork
  Spotify backend). The website player branches on `podcast.type`.

---

## Step 10 — Report

Summarize for the user:
- engine + voice used,
- `podcasts/<slug>--<locale>.mp3` path and size,
- QA verdict and overlap %,
- paths to `podcasts/<slug>--<locale>.json`, `podcasts/<slug>--<locale>.transcript.json`, and
  `podcasts/<slug>--<locale>.podcast.json`.
- Suggested next step: `/content-podcast-review <slug>`.

---

## Pitfalls

| ❌ Mistake | ✅ Correct |
|---|---|
| Reading the article 1:1 (audiobook) | Triage to the valuable ideas; companion, not transcript |
| Stretching to fill time / cutting to hit a target | Let value decide length — "just enough" |
| Leaving raw tokens (`T0`, `OpenAPI`, `50%`, `v1.2`) | Say them: "the first job", "open A.P.I.", "fifty percent", "version one point two" |
| Reading code/config syntax aloud | Say what it *does*, not the syntax; signpost to the page |
| Reading URLs / "see the diagram" aloud | Convert to plain spoken words; skip visual-only refs |
| Passing `--voice clip.wav` with `--engine kokoro` | Kokoro can't clone — use `--voice-name`, ignore the clip |
| Passing `--engine` to `call_remote.py` | `--engine` is the *command*-level flag; `call_remote.py render` itself takes `--backend` (Step 7 uses it). Map `--engine X` → `--backend X`; passing `--engine` to the script errors with `unrecognized arguments` |
| Emitting a line with no terminal punctuation | Every `line` ends in `.` `!` `?` or the render aborts |
| Treating QA `< 85%` as a hard failure | It's a review flag; surface mismatches, let a human judge |
| Trusting a high overlap % to mean "no drops" | A high overlap can still hide a localized one-sentence clip (e.g. a hyphenated compound); the independent critic's segment inspection is the backstop |
| Hardcoding the URL/token | Read `PODCAST_URL` / `PODCAST_TOKEN`; ask if unset |
| Using kokoro/chatterbox for a VI draft | VI drafts default to `vieneu`; kokoro produces broken Vietnamese pronunciation |
| Using vieneu/omnivoice for an EN draft | EN drafts default to `kokoro`; vieneu voices are trained on Vietnamese only |
| Running omnivoice without `PODCAST_VI_VOICE` + `PODCAST_VI_REF_TEXT` | OmniVoice picks a random voice per turn → different speaker every sentence. Stop and ask user to set both env vars before rendering |
| Writing output next to the input draft | All output goes under `podcasts/`, never next to the draft |
