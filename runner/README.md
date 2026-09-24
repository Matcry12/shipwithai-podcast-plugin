# Runner as a user service

`actions-runner.service` keeps the GitHub Actions runner alive without sudo.
It is a **user** unit, not `svc.sh`'s system one: it runs inside the login
session, so the browser stage reaches Chrome through the real `DISPLAY` and
session bus rather than values copied into `~/actions-runner/.env`.

```bash
mkdir -p ~/.config/systemd/user
cp runner/actions-runner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now actions-runner
loginctl enable-linger "$USER"      # once; otherwise it stops at logout
```

Check: `systemctl --user is-active actions-runner` → `active`.
Logs:  `journalctl --user -u actions-runner -f`.

Verified 2026-09-12: `kill -9` on the listener, back in ~10s, `NRestarts=1`.
Before this a network blip killed the nohup'd runner and every job queued
silently until someone looked.

## macOS (Mac mini)

`scripts/setup-mac.sh` does everything below except the logins and the runner
token; the rest of this section is what it automates.

Or let Claude drive the script -- at the Mac, or from a GitHub Actions job on
it (the site repo's `mac.yml`, with `CLAUDE_CODE_OAUTH_TOKEN` as a repo secret
and `claude -p` in skip-permissions mode, since nobody is there to approve).
Either way the prompt is:

```
Set this Mac up as the podcast CI runner. Download and run
https://raw.githubusercontent.com/Matcry12/shipwithai-podcast-plugin/master/scripts/setup-mac.sh
(download first, then `bash setup-mac.sh`; it is safe to rerun). Fix anything it
reports missing. Run the doctor it prints and fix every red line you can. Never
type any password for me. Anything that needs sudo, a keyboard, or a login
(GitHub, Spotify in the dedicated Chrome on port 9333) you cannot do: skip it and
list it at the end. If this Mac is not yet a runner, list that too: registering
needs a token from GitHub -> Settings -> Actions -> Runners, then
`./config.sh --labels podcast --unattended` in ~/podcast/runner and
`./svc.sh install && ./svc.sh start`.
```

No systemd. The runner's own `svc.sh` installs a **LaunchAgent** here (not a
system daemon), which already runs inside the logged-in GUI session — so use it:

```bash
cd ~/actions-runner
./svc.sh install && ./svc.sh start
./svc.sh status
```

Logs: `~/actions-runner/_diag/`. The agent only runs while that user is logged
in, so the box must auto-login and never sleep:

```bash
sudo pmset -a sleep 0 disksleep 0 displaysleep 10
# System Settings -> Users & Groups -> Automatic login -> <this user>
```

`~/actions-runner/.env` needs no DISPLAY/XAUTHORITY/DBUS lines. Instead point
browser-harness at a dedicated Chrome that was launched with a debugging port —
that Chrome never shows the "Allow remote debugging?" popup which stalled
unattended runs on Linux:

```
PATH=/Users/<you>/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
PODCAST_REPO=/Users/<you>/Developer/shipwithai-podcast-plugin
BU_NAME=podcast
BU_CDP_URL=http://127.0.0.1:9333
HOME=/Users/<you>
LANG=en_US.UTF-8
```

Keep that Chrome alive across reboots with `~/Library/LaunchAgents/podcast.chrome.plist`
(`KeepAlive`, args `--remote-debugging-port=9333 --user-data-dir=$HOME/podcast/chrome-profile`),
then log into Spotify for Creators in it **once** — the profile persists.

### The shared Mac, as actually set up (2026-09-17)

`minigala-4` was set up entirely through GitHub Actions — no hands on the box.
The full record with every run id is `runner/mac-plan.md`. What matters later:

**Footprint** — everything the pipeline owns on that Mac, nothing else:

```
~/podcast/                      plugin clone (+ .env, voices/), browser-harness, chrome-profile,
                                claude/ (CLAUDE_CONFIG_DIR), cli/ (the claude CLI, npm build)
~/Library/LaunchAgents/podcast.chrome.plist   the :9333 Chrome, KeepAlive
~/.local/bin/browser-harness    uv tool install (+ ~/.local/share/uv/tools/browser-harness)
brew: bash, uv                  (and bash's deps gettext json-c libunistring ncurses); claude-code cask upgraded
```

The owner's `~/.claude`, `gh` login, system settings and runner install
(`~/Documents/Mangala/actions-runner`) are untouched. The runner is the x64
build under Rosetta, so the workflow runs `ci-podcast.sh` via `arch -arm64`.

**`claude` comes from npm, not the cask.** On 2026-09-24 the cask's single-file
binary (2.1.267) hung at startup on this Mac: *every* invocation, `--help`
included, parked before reaching its own code — no files opened, no stack to
sample, 87 minutes on one job before anyone noticed. Ruled out: version,
architecture (reinstalled native arm64), Gatekeeper/quarantine,
`CLAUDE_CONFIG_DIR`, `HOME`, auto-update traffic, disk, DNS. The npm build of
the same CLI answers in two seconds, so both workflows put it first on `PATH`:

```bash
npm install --prefix ~/podcast/cli @anthropic-ai/claude-code   # → ~/podcast/cli/node_modules/.bin/claude
```

Same command upgrades it. The cask is left installed but unused; if a later
cask version starts working, drop the PATH entry in `podcast.yml` and
`mac.yml`. Preflight now caps this check at 60s, so this failure mode is a red
job in a minute, not a silent hour.

**Rollback** — one `mac.yml` dispatch removes all of it:

```
launchctl unload ~/Library/LaunchAgents/podcast.chrome.plist; rm -f ~/Library/LaunchAgents/podcast.chrome.plist
rm -rf ~/podcast ~/.local/bin/browser-harness ~/.local/share/uv/tools/browser-harness   # ~/podcast/cli goes with it
brew uninstall bash uv && brew autoremove
```

**Remote shell** — `mac.yml` in the site repo (`workflow_dispatch`, input `cmd`,
gated to one GitHub account). Every check below is a dispatch of it:

```bash
gh workflow run mac.yml -R truongnguyenptit/shipwithai.io --ref demo/podcast-auto -f cmd='<shell>'
```

**A daily heartbeat watches all of this.** `podcast-health.yml` (site repo)
runs `runner-doctor.sh` on the Mac every morning — about thirty seconds, no
rendering, no publishing — so a dependency that rotted overnight is a red tick
rather than a post that quietly fails to become an episode. It has a second
job on GitHub's own machines, because the Mac-side check cannot report that
the Mac is gone: with no runner the job just queues, and silence looks exactly
like health. That job fails when no health run has succeeded in 36 hours.

The cron only fires from the repository's default branch, so it starts working
when the workflow is merged there.

**Two recurring chores**, both remote:

1. *Claude token* (~yearly): on the PC `claude setup-token`, then
   `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R <site repo>`. A 401 in the
   preflight is the symptom.
2. *Spotify session* (weeks–months): the publish stage fails at Spotify, or
   this dispatch says `NOT logged in`:
   ```
   BU_CDP_URL=http://127.0.0.1:9333 BU_NAME=podcast arch -arm64 browser-harness <<PY
   new_tab("https://creators.spotify.com/home/show/<showId>"); wait_for_load()
   u = page_info()["url"]; print("logged in" if u.startswith("https://creators.spotify.com/home/show/") else "NOT logged in -> " + u[:80])
   PY
   ```
   Re-login without touching the Mac: log into Spotify in the PC's own :9333
   Chrome (`systemctl --user start podcast-chrome`), export the `spotify.com`
   cookies with browser-harness (`cdp("Network.getAllCookies")`) to a file,
   `gh secret set SPOTIFY_COOKIES < file`, dispatch
   `cdp("Storage.setCookies", cookies=...)` into the Mac's Chrome, then
   **delete the secret and the file** — the cookies are the account, and every
   repo writer can read a secret.

## Linux: the same dedicated Chrome

Chrome 144+ shows "Allow remote debugging?" on every attach to a normal
profile; Allow never sticks. `podcast-chrome.service` launches a separate
Chrome with the port flag (no popup) and its own profile (the pipeline stops
driving the Chrome you work in):

```bash
cp runner/podcast-chrome.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now podcast-chrome
```

Log into Spotify for Creators in the window it opens, once. Then add to
`~/actions-runner/.env` and restart the runner service:

```
BU_NAME=podcast
BU_CDP_URL=http://127.0.0.1:9333
```
