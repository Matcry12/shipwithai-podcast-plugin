# 32 — Podcast Workflow Tutorial (how to actually use it)

> A hands-on guide for anyone who pulled this repo and wants to turn a blog post
> into a podcast. Read this before your first run. It covers the happy paths
> **and** every place people get it wrong.

If you want the internal mechanics (server setup, QA overlap %, R2 config), read
[`docs/31-content-podcast-pipeline.md`](31-content-podcast-pipeline.md). **This**
doc is the user tutorial: which command to say, when, and what *not* to expect.

---

## 1. The one-paragraph mental model

A podcast here is a **spoken companion** to the article — the genuinely valuable
ideas, rewritten for the ear so they work with your eyes closed. It is **not** a
text-to-speech read-aloud of the post, and it is **not** a generic "make me a
podcast" video/audio generator. It is produced by *this plugin's* flow, from a
draft *this plugin* already wrote and reviewed.

---

## 2. Three requests, two commands, one rule

This is the single most important table in this doc. Almost every mistake comes
from picking the wrong row.

| What you want | Say this |
|---|---|
| A podcast from a draft that **already exists** (already reviewed + seo'd) | `/content-podcast-all drafts/<slug>--en.md` (or `--vi.md`) |
| A blog post **and** its podcast, starting **from a topic** | `/content-pipeline "<topic>" --archetype <id> --locale en --podcast` |
| Just the blog post, no podcast | `/content-pipeline "<topic>" --archetype <id> --locale en` |

**The rule:** `/content-podcast-all` works on an **existing** draft. `/content-pipeline`
starts **from a topic** and writes the draft first. If you already have the draft,
never reach for `/content-pipeline` — it would try to write a new one.

**The other rule:** in a combined run, **the podcast covers whatever locales the
blog produced.** `--locales en,vi --podcast` gives you an EN podcast *and* a VI
podcast.

---

## 3. Before your first run — prerequisites

The flow will **stop at preflight** (rendering nothing) if any of these is missing.
Set them up once:

| Requirement | How |
|---|---|
| `PODCAST_URL` + `PODCAST_TOKEN` | The render server prints both on startup. Put them in `.env` (never commit — only `.env.example` is tracked). See [docs/31 §Prerequisites](31-content-podcast-pipeline.md). |
| A reachable render server | Someone runs it (`setup.command` / `start.command`) and shares the ngrok URL + token. |
| `requests` Python package | `pip install requests` |
| `ffmpeg` — **only for `--mode dialogue`** | `brew install ffmpeg` (macOS) / `sudo apt install ffmpeg`. Dialogue concatenates speaker turns with it; single narrator never needs it. |
| Cloned voices — **only for dialogue** | `PODCAST_<LOCALE>_VOICE` + `_VOICE_2` (and `_REF_TEXT`/`_REF_TEXT_2`) in `.env`. Without `_VOICE_2` both speakers use the *same* voice. |
| A draft that passed review + SEO | Run `/content-review` then `/content-seo` first. |
| Correct locale on the draft | Filename `--en`/`--vi` suffix **and** `locale:` frontmatter must agree (EN or VI only). |

If you're not sure whether these are set, just run `/content-podcast-all` — it
checks all of them up front and tells you exactly what's missing before doing any
work.

---

## 4. Path A — podcast from an existing draft (most common)

You have `drafts/claude-code-hooks--en.md`, already reviewed and seo'd.

```
/content-podcast-all drafts/claude-code-hooks--en.md
```

What happens, in order:

1. **Preflight** — checks env vars, `requests`, locale gate, and that the draft
   passed review+seo. Fails fast with the fix if anything's off. **Renders nothing
   until this passes.**
2. **Render** — `/content-podcast` triages the draft to what's worth hearing,
   rewrites it for the ear, makes every token sayable, renders the `.mp3`, runs
   Whisper QA.
3. **Review** — `/content-podcast-review` grades it independently. **This is a
   hard gate:** if the verdict is `fix` or `regenerate`, the flow **stops and does
   not post**. You address the findings (or re-render) and re-run.
4. **Post** (only on a `ship` verdict) — `/content-podcast-posting` uploads to
   Spotify. **This pauses for your confirmation** before publishing.
5. **Stop.** It tells you `/content-publish` will embed the player in the post.

Dialogue instead of single narrator:

```
/content-podcast-all drafts/claude-code-hooks--en.md --mode dialogue
```

---

## 5. Path B — blog + podcast from a topic

You have no draft yet, just a topic.

```
/content-pipeline "claude code pre-commit hooks" --archetype tutorial --locale en --podcast
```

This runs the **whole blog spine** (idea → brief → write → review → seo →
humanize) and then, at stage 6.5, renders + reviews + posts the podcast, and
finally publishes the post with the player embedded.

Both locales at once:

```
/content-pipeline "claude code pre-commit hooks" --archetype tutorial --locales en,vi --podcast
```

You get an EN post + EN podcast **and** a VI post + VI podcast. Posting pauses
once per locale (twice here) — that's expected.

---

## 6. Doing it by hand (the three stages)

`/content-podcast-all` just sequences these. Run them individually when you want
control between steps:

```
/content-podcast drafts/<slug>--en.md              # render + QA
/content-podcast-review <slug>--<locale>            # independent gate — must say ship
/content-podcast-posting <slug>--<locale>           # upload (confirm gate)
```

Then `/content-publish drafts/<slug>--en.md` embeds the block.

---

## 7. Common misunderstandings (read this part)

**"It'll just read my whole article out loud."**
No. It's a *companion* — it keeps the valuable ideas and rewrites them for the
ear. Expect it to be shorter and different from the article, by design.

**"I already have a draft, so I'll run `/content-pipeline --podcast`."**
Wrong command. `/content-pipeline` starts from a *topic* and writes a *new* draft.
For an existing draft use `/content-podcast-all`.

**"`/content-pipeline --podcast` only does English."**
Not anymore. It podcasts **every locale it rendered**. `--locales en,vi --podcast`
= two podcasts.

**"I said 'make me a podcast' and it ran some other skill / a video generator."**
Be explicit: name the draft and use `/content-podcast-all` (or `/content-podcast`).
Those bind to *this* plugin's flow. A bare "make a podcast" can look like a generic
globally-installed skill — pointing at a `drafts/…` file removes the ambiguity.

**"It refused because my draft isn't reviewed."**
Correct behavior. Podcasts are only made from drafts that passed `/content-review`
**and** `/content-seo`. Run those first.

**"It refused at Step 0 about locale."**
Your filename suffix (`--en` / `--vi`) and the `locale:` frontmatter must **agree**,
and must be EN or VI. A `--en.md` file with `locale: vi` (or a locale that isn't
EN/VI) is rejected on purpose.

**"It posted to Spotify but nothing shows on the blog."**
Posting and blog-publishing are different steps. Posting puts the episode on
Spotify and fills the metadata stub. `/content-publish` is what injects the player
into the blog post's frontmatter. Run it after.

**"I put `--podcast` in a cron job and it hung."**
`--podcast` makes the run **interactive** (Spotify has a human confirm gate). Never
use it in cron/CI. For unattended blog runs, drop `--podcast`.

**"The review said fix but it posted anyway."**
It won't. Posting is hard-gated on the `ship` verdict. `fix`/`regenerate` stops the
flow before posting.

**"The podcast failed and it killed my whole blog pipeline."**
It won't. In `/content-pipeline`, the podcast stage is **best-effort** — a failed
render, a declined gate, or an exhausted critic loop logs and the pipeline still
publishes the post (just without the embed).

**"Where are my files? They're not in git."**
Everything lands under `podcasts/` which is **gitignored** (drafts and briefs too).
That's intentional — they're generated artifacts, not shipped source.

**"Which engine should I pass?"**
Default (`kokoro`) is fine and fast. `--mode dialogue` gives host + co-host. You
rarely need to touch `--engine`.

---

## 8. Troubleshooting preflight failures

| Message says… | Fix |
|---|---|
| `PODCAST_URL` / `PODCAST_TOKEN` unset | Add them to `.env` from the render server's startup output. |
| `requests` not importable | `pip install requests` |
| Draft is not EN or VI / locale mismatch | Fix the `--en`/`--vi` suffix or the `locale:` frontmatter so they agree. |
| Draft hasn't passed review/seo | Run `/content-review` then `/content-seo` on the draft first. |
| Render server unreachable | **The most common failure.** The ngrok URL *and* token rotate every time the host restarts `start.command`, so a `.env` that worked yesterday goes stale silently. Get the current pair, update `.env`, then `set -a; source .env; set +a`. |
| `ffmpeg` not found (dialogue only) | `brew install ffmpeg` / `sudo apt install ffmpeg`, or drop `--mode dialogue`. |
| Warning: `PODCAST_<LOCALE>_VOICE_2` unset | Not a failure — but host and co-host will sound **identical**. Set the clip vars for a real two-speaker episode. |

---

## 9. Artifacts you'll get

All under `podcasts/` (gitignored):

| File | What it is |
|---|---|
| `<slug>--<locale>.json` | The render script (spoken text). |
| `<slug>--<locale>.mp3` | The rendered episode. |
| `<slug>--<locale>.transcript.json` | Whisper QA result. |
| `<slug>--<locale>.podcast.json` | Metadata stub; the `podcast` block is filled by posting and read by `/content-publish`. |

Every artifact is keyed by `<slug>--<locale>`, not bare `<slug>` — this is what
keeps an EN and a VI episode of the same post from colliding. In a multi-locale
run, `/content-publish` injects each locale's stub into its own post.

---

## 10. TL;DR

- Existing draft → `/content-podcast-all drafts/<slug>--<en|vi>.md`.
- From a topic, want both → `/content-pipeline "<topic>" --archetype <id> --locale <en|vi> --podcast`.
- It's a **companion**, not a read-aloud. It **won't post** unless review says `ship`.
  It **won't publish to the blog** until `/content-publish`. It **won't run** without
  the render server + env vars + a reviewed+seo'd EN/VI draft.
