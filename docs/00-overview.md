# 00 — Overview: why, how, what we use, what comes out, how we judge it

> Read this first. `01-pipeline.md` is the command reference, `02-workflow-tutorial.md`
> is the by-hand walkthrough, `runner/` is the CI machine. This is the design doc:
> the reasoning behind all three, and the record of what it has actually done.

---

## 1. Why this exists

shipwithai.io publishes EN and VI blog posts about building with AI tools. Every
post is a candidate for a spoken companion — not a read-aloud, a short
conversation that carries the two or three ideas worth keeping, for people who
listen while commuting or cooking and never open the page.

Doing that by hand is ~1 hour per episode: rewrite for the ear, render, listen,
fix, upload, paste the link back. Nobody keeps that up for two locales. So the
goal is:

**A pushed blog post becomes a published, embedded podcast episode with no human
in the loop, at a quality bar an editor would sign off on — or it stops and says
why.**

The two halves matter equally. Unattended publishing to a public feed with no
quality gate is worse than no podcast; a gate that needs a human to click is not
unattended.

---

## 2. How it works

### The chain

```
site repo push (blog post changed)
  │
  ▼
ci-podcast.sh  ── copies the post into drafts/<slug>--<locale>.md
  │
  ├─ [1] /content-podcast          rewrite for the ear → TTS render → Whisper QA
  ├─ [2] /content-podcast-review   independent critic → score → ship | fix | regenerate
  │        ▲                              │
  │        └── fix: patch script, re-render ─┘   (up to 3 cycles)
  │        └── regenerate: rewrite from scratch ─┘
  ├─ [3] /content-podcast-posting  publish to Spotify for Creators (drives a real browser)
  └─ [4] inject_podcast_frontmatter.py   write `podcast:` block into the post, commit [skip ci]
  │
  ▼
site rebuilds → post shows the player under its header
```

### Stage by stage

**[1] Render** (`skills/content-podcast/SKILL.md`). Claude reads the post and
writes a *script*, not a transcript: at most three key points, one takeaway
said three ways, every point anchored to a concrete example from the post.
Dialogue mode (the default in CI) gives a host who owns the material and a
co-host who pushes back and asks what a listener would ask. Everything is
converted for the ear — no URLs, no code, numbers as words, English terms kept
bare in VI. The script goes to the render server as JSON turns; the mp3 comes
back; Whisper transcribes it and the transcript is diffed against the script
(`overlapPct`) plus a tail check that the sign-off actually made it into the
audio.

**[2] Review** (`agents/podcast-critic.md`). A separate agent that has *not*
seen the render conversation scores the script and the transcript against a
fixed rubric (§5) and returns one of three verdicts. This is the only quality
gate in CI. It is deliberately a different agent with a different prompt: the
writer grading its own work found nothing wrong in every test we ran.

**[3] Publish** (`skills/content-podcast-posting/`). Spotify for Creators has
no upload API. The stage drives a logged-in Chrome through CDP
(`browser-harness`): new episode → upload mp3 → title/description from the
stub → Publish now. It searches the dashboard for a same-titled episode first
so a retried run cannot create a duplicate. `--yes-publish` skips the human
confirm; **only `ci-podcast.sh` passes it**, and only after a `ship` verdict.

**[4] Inject**. The episode URL is written as a `podcast:` block into the
post's frontmatter and committed to the same branch with `[skip ci]`. The
site's `PodcastPlayer` component renders the Spotify embed when the block is
present.

### Unattended operation

`scripts/ci-podcast.sh` is the whole CI. It diffs the push for changed posts
under `src/content/blog/{en,vi}/`, skips any already carrying a `podcast:`
block, caps the batch (`PODCAST_MAX_PER_PUSH=3`), runs a preflight (bash ≥ 4,
`.env`, render server `/health`, ffmpeg, browser-harness, `claude -p ok`), then
runs the chain per post. Every Claude call is `claude -p --model sonnet
--effort medium` — pinned, so the Mac and the PC produce the same episode for
the same push.

The workflow (`podcast.yml`, site repo) runs it on a **self-hosted Mac mini**
(`runner/mac-plan.md` has the full setup record). Self-hosted is not a
preference: the TTS server is on a private network, and publishing needs a
browser with a live Spotify session. No cloud runner can supply either.

---

## 3. What we use

| Layer | Choice | Why this one |
|---|---|---|
| Orchestration | Claude Code plugin (`commands/`, `skills/`, `agents/`), run as `claude -p` | The stages are judgment work (rewrite, critique, drive a UI), not scripts. Pinned `sonnet`/`medium`: verified 35/35 on it; Opus adds cost, not score. |
| Script → speech | Remote render server on a Mac: **OmniVoice** (voice cloning, EN + VI, the main path), **Kokoro** (EN preset fallback), Chatterbox / VieNeu (available, unused) | VI has no usable preset voice; cloning from 4 reference clips (`voices/`) is the only way the show sounds like the show in both languages. |
| Audio QA | **faster-whisper** on the same server; `overlapPct` script-vs-transcript + tail-coverage check | Cheap, deterministic, catches dropped turns and garbled identifiers before the expensive critic runs. |
| Quality gate | `podcast-critic` agent, 35-point rubric, YAML report | Independent grader; hard-fails on any invented claim. |
| Publishing | Spotify for Creators via **browser-harness** (CDP into a dedicated Chrome on `:9333`) | No API exists. A dedicated Chrome with its own profile keeps the session out of anyone's daily browser and avoids the "allow remote debugging?" prompt. Cloudflare R2 is the alternate backend (`--backend r2`) for self-hosting the mp3. |
| CI | GitHub Actions, self-hosted runner on a shared Mac mini, LaunchAgent (GUI session) | Needs LAN + GUI browser. Everything the pipeline owns lives under `~/podcast/` plus one LaunchAgent, removable with one command. |
| Secrets | Repo secrets: `CLAUDE_CODE_OAUTH_TOKEN`, `PODCAST_ENV` (the whole `.env`) | Nothing secret sits on the runner's disk except what the job writes at start. |
| Site side | Astro; `podcast` schema in `content.config.ts`; `PodcastPlayer.astro` | Player is opt-in per post — no block, no player. |

Not used, on purpose: no queue, no database, no dashboard. The durable record
of an episode is the `podcast:` block in the post. If the post has one, the
episode exists; if not, it doesn't.

---

## 4. What comes out

Per episode, on the runner (`podcasts/`, `podcast-reports/` — gitignored):

| File | What |
|---|---|
| `<slug>--<locale>.json` | the script: `host_mode`, turns `{voice, line}` |
| `<slug>--<locale>.mp3` | the episode (≈1.3 MB / 5 min VI dialogue) |
| `<slug>--<locale>.transcript.json` | Whisper output: `text`, timed `segments`, `overlapPct` |
| `<slug>--<locale>.podcast.json` | metadata stub: title, locale, engine, `qaOverlapPct`, then the Spotify URL/embed/episodeId once published |
| `podcast-reports/<slug>--<locale>.md` + `.critic.yaml` | the critic's scored report, per-cycle |

In the site repo, the one thing that lasts:

```yaml
podcast:
  type: spotify
  url: 'https://open.spotify.com/episode/4xkWvFqmxLIj6gOUAjkxhK'
  embedUrl: 'https://open.spotify.com/embed/episode/4xkWvFqmxLIj6gOUAjkxhK'
  episodeId: '4xkWvFqmxLIj6gOUAjkxhK'
```

What a reader sees: a Spotify player under the post header. What a listener
gets: a 4–6 minute two-voice conversation that stands alone without the page.

When a run **halts** (3 cycles, no `ship`): job goes red, nothing is
published, the mp3 and the critic reports are attached to the run as an
artifact for 7 days. A human reads the report and either fixes the post or
runs the stage by hand.

---

## 5. How we judge it

### The rubric (dialogue = 35, single narrator = 30)

| Dimension | Pts | What loses points |
|---|---|---|
| Faithfulness | 8 | any claim not in the post — **hard fail, always `regenerate`** |
| Value | 6 | padding, boilerplate, survey-of-everything, missing the actual point |
| Eyes-free sayability | 6 | raw identifiers, URLs, digits, code, anything that only works on a page |
| Standalone | 3 | "as shown below", "copy it from the post" with the thing never said aloud |
| Memorability | 5 | > 3 key points, no repeated takeaway, no concrete anchor, no recap |
| Conversationality (dialogue) | 5 | turns that don't react to the previous turn, unanswered questions, filler; ≤ 2/5 caps at `regenerate` |
| Render integrity | 2 | `overlapPct` < 85% with a real defect, skipped turn, garbled sentence |

### Verdicts

- **`ship`** — ≥ 28/35, faithfulness clean, overlap ≥ 85% (or judged a
  Whisper artifact), conversationality ≥ 4/5.
- **`fix`** — ≥ 26/35, faithfulness 8/8: patch the named turns and re-render.
  Also whenever the audio is missing something the script has.
- **`regenerate`** — anything else: rewrite from the post.

Minors never block. Majors that block are the ones a listener would hear:
missing audio, garbled TTS, a claim the post never made.

### Loop policy

Three render→review cycles, then halt. Three, not two: a `regenerate` followed
by a `fix` is progress and the `fix` deserves its own attempt. Three, not
more: a script that fails three independent reviews has a problem in the post,
and a human should look. We chose **halt** over "ship the best attempt" because
a duplicate or bad episode on a public feed can only be deleted by hand in the
Spotify dashboard; a red job costs nothing.

### What it has actually done

| Date | Locale / mode | Where | Cycles | Score | Time | Notes |
|---|---|---|---|---|---|---|
| 2026-09-12 | VI dialogue | PC | 2 | 34/35 | — | first VI; only the audio tail needed re-rendering — this is why cycles went 2 → 3 |
| 2026-09-17 | EN dialogue | Mac mini, unattended | 2 | 31 → **35/35** | ~50 min | c1 `fix`: sign-off missing from the audio. Published, injected, no re-trigger. |
| 2026-09-17 | VI dialogue | Mac mini, unattended | 2 | 30 → **33/35** | 26 min | c1 `fix`: "copy the template from the post" (standalone), 4 non-reactive turns. Lost 2 pts on sayability: `npm package` mangled, "Claude" pronounced "Cloud". |

Where the time goes (VI run): render 8 min, review 6.5, re-render 3.5,
re-review 3.5, publish 4. TTS and the critic's re-listen dominate; the model is
not the bottleneck. The lever is **avoiding cycle 2**: both cycle-1 failures
were the same two recurring findings, which are now rules and a check in the
render skill (commit `9f88dfe`).

Known quality ceilings, in priority order:

1. **VI voice mispronounces "Claude"** (→ "Cloud"). A voice artifact, not a
   script defect, so the critic never blocks on it — it will sound like that
   on every VI episode until the script spells it for the ear. Fix is a
   VI rule with a phonetic spelling, chosen by a short listen test.
2. Bare English identifiers in VI (`npm`) get garbled — same fix.
3. EN Kokoro fallback clips the tail of hyphenated compounds; irrelevant while
   OmniVoice is configured.

---

## 6. Decisions and why

- **Never auto-publish, except CI after `ship`.** `/content-podcast-all` stops
  at the confirm by design; CI calls the three stages separately so it can
  pass `--yes-publish` with the critic as the only gate. The flag is dangerous
  enough that it lives in exactly one call site.
- **Two loop guards.** The inject commit lands on the branch the workflow
  watches. `[skip ci]` *and* "skip any post that already has `podcast:`" —
  `[skip ci]` alone is one careless edit away from a publish storm.
- **Verify artifacts, not exit codes.** `claude -p` ends the session the
  instant the agent returns; twice the render stage backgrounded the job and
  returned 0 with no mp3. Every stage checks the file exists.
- **Model pinned.** Without `--model`/`--effort`, `claude -p` inherits whatever
  the runner's `~/.claude/settings.json` says — a different episode per
  machine for the same push.
- **The shared Mac.** It is a roommate's computer. Everything was done through
  Actions (no hands on the box), the footprint is one directory plus one
  LaunchAgent, and there is a one-line rollback. Claude's config is isolated
  (`CLAUDE_CONFIG_DIR`), the owner's `~/.claude`, `gh` login and system
  settings are untouched.
- **Spotify session by cookie hand-over, not password.** Nobody types a
  password anywhere. Cookies were exported from a logged-in PC Chrome, moved
  through a repo secret, imported into the Mac's dedicated Chrome, and the
  secret and file deleted the same hour. "Sign out everywhere" in Spotify is
  the kill switch.
- **Known risk, accepted for now:** any repo writer can read repo secrets by
  pushing a workflow. Mitigation is a GitHub environment with required
  reviewers (§7).

---

## 7. What's next

In order:

1. **Merge the site PR** (player + schema + workflows) — trigger stays on
   `demo/**`, so merging changes nothing until step 3.
2. **Point the Mac at the production show** — today it is logged into the
   tester show. Either a config change (same account) or one more cookie
   hand-over (different account).
3. **Widen the trigger** to the publishing branch. Only posts changed in the
   push are processed, so there is no backlog storm; keep
   `PODCAST_MAX_PER_PUSH` low for the first week.
4. **Failure notification** — make sure a red podcast job reaches a person.
5. **Restrict secrets** to a GitHub environment with required reviewers.
6. **VI pronunciation rules** for "Claude" / `npm` (the quality item above).
7. Cleanup: delete the demo branch and the tester episodes, decide the PC
   runner's fate, re-register the Mac runner as arm64 (cosmetic).

Not planned: a "ship anyway on cycle 3" mode. Revisit after the first real
halt, not before.

---

## 8. Map

```
commands/        the four slash commands (thin; they point at skills)
skills/          the procedures: content-podcast (render), -review, -posting, -all
agents/          podcast-critic — the independent grader and its rubric
scripts/         ci-podcast.sh (CI entry), call_remote.py / call_local.py (render + transcribe),
                 inject_podcast_frontmatter.py, runner-doctor.sh, setup-mac.sh, r2_upload.py
runner/          README (runner install, both OSes), mac-plan.md (the Mac record), service units
voices/          the four reference clips for cloning (EN host/co-host, VI host/co-host)
docs/            this file, 01 command reference, 02 tutorial
drafts/ podcasts/ podcast-reports/   working dirs, gitignored
```
