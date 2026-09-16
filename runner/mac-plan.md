# Mac runner (minigala-4) setup plan — via GitHub Actions, no hands on the Mac

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to run this plan task-by-task, in this session, with a human checkpoint after every task. Steps use checkbox (`- [ ]`) syntax for tracking. **Never run two tasks without reading the previous task's job log.**

**Goal:** make the Mac mini `minigala-4` able to run `podcast.yml` end to end, touching nothing on it outside a short, listed footprint.

**Architecture:** Every change reaches the Mac as a GitHub Actions job (`mac.yml`, `workflow_dispatch`, one `cmd` input). Each task = one dispatch that first prints the state it expects, then acts, then prints the state it produced. A task is done only when its log shows the "after" line. Anything that needs sudo, a keyboard, or a login is not attempted by a job — it is listed for the human.

**Tech stack:** GitHub Actions self-hosted runner (LaunchAgent, user `minigala`), Homebrew at `/opt/homebrew`, `scripts/setup-mac.sh`, `scripts/runner-doctor.sh`, `claude` CLI authenticated by the repo secret `CLAUDE_CODE_OAUTH_TOKEN`.

**Spec:** this file's *Global constraints* + `runner/README.md` (macOS section) + `scripts/setup-mac.sh` header comment.

## Global constraints

- **It is a roommate's computer.** Footprint is limited to the ledger below. Nothing under `/`, `/etc`, `/Library`, no sudo, no system settings, no login items other than the two listed.
- **Footprint ledger** — everything we are allowed to create on the Mac:
  - `~/podcast/` (plugin, browser-harness, voices, chrome-profile, `.env`) — one folder, `rm -rf ~/podcast` removes it all.
  - `~/Library/LaunchAgents/podcast.chrome.plist` — the dedicated Chrome. `launchctl unload` + `rm` removes it.
  - Homebrew packages: `bash`, `uv` (D3; + whatever is already there: `ffmpeg`, `gh`, `claude-code`, Google Chrome). Shared with the roommate; each is `brew uninstall`-able. **Never `brew upgrade` blanket; only named packages.**
  - ~~One line in `~/.claude/CLAUDE.md`~~ -> D1: claude config lives in `~/podcast/claude/` via `CLAUDE_CONFIG_DIR`; the roommate's `~/.claude` is never written.
  - Already touched before this plan: `brew upgrade --cask claude-code` (2.1.118 → 2.1.267) on 2026-09-16.
- **Not by a job, ever:** `sudo pmset`, `gh auth login`, Spotify login, changing runner labels, restarting the runner, `--yes-publish` outside `ci-podcast.sh`.
- **Secrets never land on the Mac's disk** except `~/podcast/plugin/.env` (already gitignored, copied by the human over SSH). The Claude token stays a GitHub secret.
- **Every dispatch is idempotent** — safe to re-run after a failure.
- Site repo: `truongnguyenptit/shipwithai.io`, branch `demo/podcast-auto`. Plugin repo: `Matcry12/shipwithai-podcast-plugin`, `master`.
- The PC runner (`matcry-b460mds3h`) is also online. Jobs meant for the Mac use `runs-on: [self-hosted, macOS]`.
- `PODCAST_URL` in `.env` is a LAN address of the render host. The Mac must sit on that LAN (or the host gets a routable/tailnet address) — no task here can fix that.

## Expected tree on the Mac when done

```
/Users/minigala/
├── podcast/                          <- Task 3 creates; `rm -rf` removes all of it
│   ├── plugin/                       git clone Matcry12/shipwithai-podcast-plugin (master)
│   │   ├── .env                      Task 4, scp from PC, voice paths rewritten
│   │   ├── scripts/                  ci-podcast.sh, runner-doctor.sh, setup-mac.sh
│   │   ├── drafts/                   per run, gitignored
│   │   ├── podcasts/                 rendered mp3+json, gitignored
│   │   └── podcast-reports/          critic reports, gitignored
│   ├── browser-harness/              git clone browser-use/browser-harness
│   ├── voices/*.wav                  Task 4, scp from PC
│   ├── chrome-profile/               Task 5, created by the dedicated Chrome
│   └── runner/.env                   setup-mac.sh writes it; inert if the runner lives elsewhere
├── Library/LaunchAgents/
│   ├── podcast.chrome.plist          Task 5 (only with the human present)
│   └── actions.runner.*.plist        already there -- the runner, untouched
│   └── claude/CLAUDE.md              D1: claude's config dir for jobs (CLAUDE_CONFIG_DIR)
└── .local/bin/browser-harness        Task 3, uv tool install

/opt/homebrew/bin/{bash,uv,jq,node,python3}   Task 3 -- only the ones missing (recon tells)
<runner root>/_work/shipwithai.io/            site checkout, made by podcast.yml itself
```

## Progress

| Task | State | Evidence |
|---|---|---|
| 1 mac.yml | done | run 35106905402: `ok-from-minigala-4.local`, `minigala`. Needed a self-registering push trigger (commit on demo/podcast-auto). |
| 2 recon | done | run 35107100696, see *Recon result*. Decisions: D1–D4 below. |
| 3 tools+clones | pending | |
| 4 voices+.env | pending | |
| 5 doctor+Chrome | pending | |
| 6 podcast.yml | pending | |
| 7 real post | pending | |
| 8 tidy | pending | |

---

### Task 0: Rollback card (read before anything)

Keep this in the log of the session. If any task leaves the Mac in a state we don't want, the undo for the *whole* plan is one dispatch:

```
launchctl unload ~/Library/LaunchAgents/podcast.chrome.plist 2>/dev/null; rm -f ~/Library/LaunchAgents/podcast.chrome.plist
rm -rf ~/podcast
sed -i '' '/browser-harness\/SKILL.md/d' ~/.claude/CLAUDE.md 2>/dev/null
brew uninstall bash uv 2>/dev/null   # D3: the only two Task 3 installs
ls ~/podcast ~/Library/LaunchAgents/podcast.chrome.plist 2>&1
```

Expected after: both `ls` lines say `No such file or directory`.

---

### Task 1: `mac.yml` — the remote shell

**Files:**
- Create: `truongnguyenptit/shipwithai.io:.github/workflows/mac.yml` (branch `demo/podcast-auto`)

**Interfaces:**
- Produces: `gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='…'` — every later task uses exactly this.

- [ ] **Step 1: the human creates the file** (the assistant's permission classifier refuses to write a run-anything workflow — by design):

```yaml
name: Mac
# Remote shell on the Mac runner. Runs as the runner's user inside its GUI
# session: brew, git, launchctl, files all work; sudo and logins do not.
on:
  workflow_dispatch:
    inputs:
      cmd:
        description: shell to run on the Mac
        required: true
jobs:
  run:
    # Write access to this repo must not be a shell on someone's desk.
    if: github.actor == 'Matcry12'
    runs-on: [self-hosted, macOS]
    timeout-minutes: 30
    env:
      PATH: /opt/homebrew/bin:/Users/minigala/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    steps:
      - run: ${{ inputs.cmd }}
```

- [ ] **Step 2: commit and push**

```bash
cd ~/Developer/shipwithai.io && git add .github/workflows/mac.yml && git commit -m "ci: mac.yml -- dispatchable remote shell on the Mac runner" && git push origin demo/podcast-auto
```

- [ ] **Step 3: smoke dispatch (changes nothing)**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='echo ok-from-$(hostname); whoami'
```

- [ ] **Step 4: verify** — read the log with the helper below (used by every task):

```bash
# maclog: wait for the newest mac.yml run and print its step output
maclog() { cd ~/Developer/shipwithai.io; sleep 10; id=$(gh run list -R truongnguyenptit/shipwithai.io --workflow mac.yml -L 1 --json databaseId -q '.[0].databaseId'); until [ "$(gh run view $id -R truongnguyenptit/shipwithai.io --json status -q .status)" = completed ]; do sleep 5; done; j=$(gh run view $id -R truongnguyenptit/shipwithai.io --json jobs -q '.jobs[0].databaseId'); echo "run=$id $(gh run view $id -R truongnguyenptit/shipwithai.io --json conclusion -q .conclusion)"; gh api repos/truongnguyenptit/shipwithai.io/actions/jobs/$j/logs | sed 's/^[^ ]* //' | grep -vE '^\s*$|##\[|\[36;1m'; }
maclog
```

Expected: `run=… success`, `ok-from-minigala-4.local`, `minigala`. Anything else → stop, do not continue.

---

### Task 2: Recon — record the Mac's state before touching it

**Interfaces:**
- Produces: the "before" snapshot pasted into this plan under *Recon result* (below), which Tasks 3–6 compare against.

- [ ] **Step 1: dispatch (read-only, no writes)**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
echo "== runner root ==";  echo "$RUNNER_TOOL_CACHE" | sed "s#/_work/_tool##"
echo "== labels ==";       cat "$(echo "$RUNNER_TOOL_CACHE" | sed "s#/_work/_tool##")/.runner" | tr -d "\n"; echo
echo "== ~/podcast ==";    ls -la ~/podcast 2>&1
echo "== launchagents =="; ls ~/Library/LaunchAgents 2>&1
echo "== brew ==";         brew --version | head -1; brew list --formula | tr "\n" " "; echo; brew list --cask | tr "\n" " "; echo
echo "== tools ==";        for b in bash uv jq node python3 ffmpeg gh claude browser-harness; do printf "%-15s %s\n" $b "$(command -v $b || echo MISSING)"; done
echo "== bash ==";         /opt/homebrew/bin/bash --version 2>&1 | head -1
echo "== gh auth ==";      gh auth status 2>&1 | head -3
echo "== chrome app ==";   ls -d "/Applications/Google Chrome.app" 2>&1
echo "== port 9333 ==";    curl -s -m 2 http://127.0.0.1:9333/json/version | head -c 200; echo
echo "== disk ==";         df -h ~ | tail -1
echo "== claude.md ==";    cat ~/.claude/CLAUDE.md 2>&1 | head -5'
maclog
```

- [ ] **Step 2: paste the output into *Recon result* at the bottom of this file and commit the plan.** Decide from it:
  - `~/podcast` exists with unknown content → **stop, ask the human** whose it is.
  - Runner root ≠ `~/podcast/runner` → fine; note it. (`setup-mac.sh`'s runner `.env` is then unused; Task 6 puts the env into `podcast.yml` instead.)
  - Labels line lacks `podcast` → expected; Task 6 handles it.
  - Anything under `brew list` we'd install already present → Task 3 will report `ok`, install nothing.

---

### Task 3: `setup-mac.sh`, tools and clones only (no Chrome yet)

**Files:**
- Modify: `scripts/setup-mac.sh` — add a `SKIP_CHROME=1` guard so the LaunchAgent step can be run separately (Task 5) once the human is ready to log in at the Mac. Chrome popping up unattended on a roommate's screen, with KeepAlive, is the "stupid thing" this plan exists to avoid.

**Interfaces:**
- Consumes: Task 2 tool list.
- Produces: `~/podcast/plugin`, `~/podcast/browser-harness`, `browser-harness` on PATH, `/opt/homebrew/bin/bash` 5.x.

- [ ] **Step 1: guard the Chrome step** in `scripts/setup-mac.sh` — the `if $MAC; then` block that writes `podcast.chrome.plist` becomes:

```bash
if $MAC && [ -z "${SKIP_CHROME:-}" ]; then
```

and the block's closing message documents it: `SKIP_CHROME=1 bash setup-mac.sh  # everything except the dedicated Chrome`. Commit + push to plugin `master`:

```bash
cd ~/Developer/shipwithai-podcast-plugin && git commit -am "setup-mac: SKIP_CHROME=1 runs everything except the dedicated Chrome" && git push origin master
```

- [ ] **Step 2: dispatch**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
cd ~ && curl -fsSLO https://raw.githubusercontent.com/Matcry12/shipwithai-podcast-plugin/master/scripts/setup-mac.sh
brew list --formula > "$RUNNER_TEMP"/brew-before.txt
SKIP_CHROME=1 bash setup-mac.sh
echo "== brew installed by this run =="; comm -13 "$RUNNER_TEMP"/brew-before.txt <(brew list --formula)
echo "== after =="; ls ~/podcast; /opt/homebrew/bin/bash --version | head -1; command -v browser-harness; rm ~/setup-mac.sh'
maclog
```

- [ ] **Step 3: verify** the log ends with:
  - `== brew installed by this run ==` followed by a short list — **write that list into the Task 0 rollback card** (replace `bash uv jq node python3` with what was actually installed).
  - `plugin browser-harness runner` under `ls ~/podcast`
  - `GNU bash, version 5.…`
  - a path for `browser-harness`
  - `github login` step said `ok gh` or `skipped (no tty)` — either is fine.
  - `never sleep` said `skipped (no tty)` — expected; it's on the human list.

  Missing any → re-dispatch once (idempotent). Still missing → stop and read the full log; do not "fix it with claude" yet.

---

### Task 4: Voices and `.env` — over SSH from the PC, not via GitHub

**Interfaces:**
- Consumes: PC files `~/voice_lab/voices/*.wav` and `~/Developer/shipwithai-podcast-plugin/.env`.
- Produces: `~/podcast/voices/*.wav`, `~/podcast/plugin/.env` with voice paths rewritten to `/Users/minigala/podcast/voices`.

Why SSH: `.env` holds `PODCAST_TOKEN` and R2 keys; voices are binary. Neither belongs in a GitHub secret or a job log. The human copies; a job only verifies.

- [ ] **Step 1 (human, on the PC):**

```bash
scp -r ~/voice_lab/voices minigala@minigala-4.local:~/podcast/ && scp ~/Developer/shipwithai-podcast-plugin/.env minigala@minigala-4.local:~/podcast/plugin/.env
```

- [ ] **Step 2: dispatch — rewrite paths, verify without printing secrets**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
sed -i "" "s#/home/matcry/voice_lab/voices#$HOME/podcast/voices#g" ~/podcast/plugin/.env
echo "== voices =="; ls ~/podcast/voices
echo "== env keys =="; cut -d= -f1 ~/podcast/plugin/.env | grep -v "^#" | tr "\n" " "; echo
echo "== voice paths resolve =="; grep VOICE= ~/podcast/plugin/.env | cut -d= -f2 | tr -d "\"" | while read f; do [ -f "$f" ] && echo "ok $f" || echo "MISSING $f"; done'
maclog
```

- [ ] **Step 3: verify**: every voice line says `ok`, `env keys` lists `PODCAST_URL PODCAST_TOKEN PODCAST_EN_VOICE …` and no values appear anywhere in the log.

---

### Task 5: Doctor, then the dedicated Chrome (human present)

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces: `runner-doctor.sh` exit 0 except the Chrome/Spotify line; then the LaunchAgent + a Spotify-logged-in profile.

- [ ] **Step 1: doctor dispatch (read-only)**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
cd ~/podcast/plugin && BU_CDP_URL=http://127.0.0.1:9333 bash scripts/runner-doctor.sh; echo "doctor exit=$?"'
maclog
```

Expected: every line green except the browser/CDP one (Chrome isn't up yet). Any other red → fix that one thing with a targeted dispatch, re-run the doctor. **Only if a red line resists two targeted attempts**, hand it to claude, scoped to that line:

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
cd ~/podcast/plugin && claude -p --dangerously-skip-permissions "Run: bash scripts/runner-doctor.sh. Fix ONLY the red line about <X>. Stay inside ~/podcast and brew; no sudo, no logins, do not touch Chrome. Print the doctor output again at the end."'
```

- [ ] **Step 2: Chrome — dispatch only when the human is at the Mac (or on Screen Sharing)**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
cd ~ && curl -fsSLO https://raw.githubusercontent.com/Matcry12/shipwithai-podcast-plugin/master/scripts/setup-mac.sh && bash setup-mac.sh; rm ~/setup-mac.sh
sleep 5; curl -s -m 3 http://127.0.0.1:9333/json/version | head -c 200; echo'
maclog
```

Expected: `"Browser": "Chrome/…"` JSON — the debugging port answers. A Chrome window is now open on the Mac.

- [ ] **Step 3 (human, at the Mac):** in *that* window (blank page, port 9333) log into Spotify for Creators. Type nothing anywhere else. Also, once: `sudo pmset -a sleep 0 disksleep 0 displaysleep 10`.

- [ ] **Step 4: verify login from a job — no credentials involved, just "is the session there"**

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
cd ~/podcast/plugin && BU_CDP_URL=http://127.0.0.1:9333 bash scripts/runner-doctor.sh; echo "doctor exit=$?"'
maclog
```

Expected: `doctor exit=0`.

---

### Task 6: Point `podcast.yml` at the Mac

**Files:**
- Modify: `truongnguyenptit/shipwithai.io:.github/workflows/podcast.yml:21` (`runs-on`) and `:40-50` (run + env)

**Interfaces:**
- Consumes: `ci-podcast.sh` reads `PODCAST_REPO`, `BU_CDP_URL`, `BU_NAME`, `PATH` — until now from the runner's `.env`, which the Mac's runner (root recorded in Task 2) never got. Putting them in the job env removes the need to restart any runner.

- [ ] **Step 1: edit `podcast.yml`**

```yaml
    runs-on: [self-hosted, macOS]     # was [self-hosted, podcast]; the PC runner is also online
    …
      - name: Render, review, publish, inject
        run: "$HOME/podcast/plugin/scripts/ci-podcast.sh"
        env:
          PATH: /opt/homebrew/bin:/Users/minigala/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
          BU_NAME: podcast
          BU_CDP_URL: http://127.0.0.1:9333
          LANG: en_US.UTF-8
          SITE_REPO: ${{ github.workspace }}
          BEFORE: ${{ github.event.before }}
          AFTER: ${{ github.event.after }}
          BRANCH: ${{ github.ref_name }}
          GH_TOKEN: ${{ github.token }}
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          JOB_TIMEOUT_MIN: 360
```

- [ ] **Step 2: commit + push** (no post changed → this push does not trigger a podcast run):

```bash
cd ~/Developer/shipwithai.io && git commit -am "ci: podcast job runs on the Mac; env from the workflow, not the runner's .env" && git push origin demo/podcast-auto
```

- [ ] **Step 3: the exact preflight `ci-podcast.sh` will run, via mac.yml** (the script itself exits before preflight when no post arrived, so replay its four checks — same commands, same order, from `scripts/ci-podcast.sh:139-154`):

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='
set -a; . ~/podcast/plugin/.env; set +a
/opt/homebrew/bin/bash -c "echo bash=\$BASH_VERSION"
[ -n "$PODCAST_URL" ] && [ -n "$PODCAST_TOKEN" ] && echo "env ok" || echo "env MISSING"
curl -fsS --max-time 10 -H "Authorization: Bearer $PODCAST_TOKEN" "$PODCAST_URL/health" >/dev/null && echo "render server ok" || echo "render server UNREACHABLE at $PODCAST_URL"
command -v ffmpeg && command -v browser-harness
claude -p "reply with the single word: ok"
curl -s -m 3 http://127.0.0.1:9333/json/version >/dev/null && echo "chrome ok" || echo "chrome DOWN"'
maclog
```

Expected: `bash=5.…`, `env ok`, `render server ok`, two paths, `ok`, `chrome ok`. `render server UNREACHABLE` means the Mac is not on the render host's LAN (or the host is asleep) — a network fact, not a Mac-setup one; see Global constraints.

---

### Task 7: One real post, end to end, watched

- [ ] **Step 1 (human):** push one small EN post to `demo/podcast-auto` under `src/content/blog/en/` — the same kind used in run 34850918783.

- [ ] **Step 2: watch it** (`podcast.yml` run, not mac.yml):

```bash
cd ~/Developer/shipwithai.io && id=$(gh run list -R truongnguyenptit/shipwithai.io --workflow podcast.yml -L 1 --json databaseId -q '.[0].databaseId'); gh run watch $id -R truongnguyenptit/shipwithai.io --exit-status; gh run view $id -R truongnguyenptit/shipwithai.io --log | grep -E '\[[1-4]/4\]|verdict|published|DONE|FAIL' | cut -c1-160
```

Expected: `[1/4]`…`[4/4]`, verdict `ship`, one `published`, the `[skip ci]` commit lands on the branch with a `podcast:` block. This is the **only** step that publishes; nothing before it can.

---

### Task 8: Tidy

- [ ] Delete `hello.yml` from the site repo (it did its job): `git rm .github/workflows/hello.yml`, commit, push.
- [ ] Keep `mac.yml` — it is the maintenance path (token renewal check, doctor, `brew upgrade --cask claude-code`).
- [ ] Add the *Footprint ledger* and the Task 0 rollback card to `runner/README.md` macOS section, so the next person knows exactly what is on that Mac and how to remove it.
- [ ] PC runner: leave it stopped (`systemctl --user stop actions-runner`) or leave it; with `runs-on: [self-hosted, macOS]` it can no longer take podcast jobs.

---

## Recon result (2026-09-16, run 35107100696)

```
runner root   /Users/minigala/Documents/Mangala/actions-runner   (runner 2.337.0; .runner has no labels field any more)
~/podcast     does not exist
LaunchAgents  ai.openclaw.gateway, com.google.*, com.trycua.lume_daemon   (all the roommate's; port 9333 free)
brew 7.0.2    formulae incl. ffmpeg gh node@22 python@3.11 coreutils imagemagick cloudflared; casks android-cli claude-code stats
tools         bash=/bin/bash(3.2)  uv=MISSING  jq=/usr/bin/jq  node=/opt/homebrew/bin/node  python3=/usr/bin/python3
              ffmpeg ok  gh ok  claude=/opt/homebrew/bin/claude (2.1.267)  browser-harness=MISSING
/opt/homebrew/bin/bash   missing
gh auth       logged in as linhvnguyen9  (the roommate's GitHub account)
Chrome        /Applications/Google Chrome.app present
disk          156 GiB free
~/.claude/CLAUDE.md   exists, the roommate's own content ("Tool discipline" rules)
arch          Apple M4, but the job runs as x86_64 -- the runner is the x64 build under Rosetta
```

### Decisions from recon

- **D1 — `~/.claude` is the roommate's. Do not write to it.** Jobs set `CLAUDE_CONFIG_DIR=/Users/minigala/podcast/claude` (in `mac.yml` and `podcast.yml` env), so claude's memory file, settings and session transcripts all live under `~/podcast/`. `setup-mac.sh` writes its one import line to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/CLAUDE.md`. (The three hello runs already left session files under the roommate's `~/.claude/projects/`; harmless, noted.) Ledger updated: the `~/.claude/CLAUDE.md` line is **out**, `~/podcast/claude/` is **in**.
- **D2 — `gh` on the Mac is the roommate's login.** `podcast.yml` sets `GH_TOKEN`, which `gh` prefers over the keyring, so CI never acts as them. `mac.yml` dispatches must not call `gh` for anything but `gh auth status`.
- **D3 — Task 3 will install exactly two brew formulae: `bash`, `uv`.** jq/node/python3 are already present (system or brew). Rollback card updated accordingly.
- **D4 — Rosetta.** The runner is the x64 build on an M4; every job is an x86_64 process. Homebrew re-execs itself as arm64 (it already upgraded claude fine) and macOS execs arm64 binaries from x86 shells, so nothing to do. If a native tool ever misbehaves, the fix is re-registering the arm64 runner -- a human task, not ours.
