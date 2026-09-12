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
