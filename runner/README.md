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
