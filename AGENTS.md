# HUTContentSniffer — agent notes

Persistent context for Cursor agents (Composer, etc.) working on this repo.

## What this project does

Cron-friendly Python script that watches the EA NHL 26 HUT forum for new **Content** posts from **Community Manager** authors and sends email alerts.

Monitored URL (defined in `sniff.py` as `FORUM_URL`):

https://forums.ea.com/category/nhl-26-en/discussions/nhl-26-ultimate-team-en?messages.widget.messagelistfornodebyrecentactivitywidget-tab-main-sojpns-1=newest

Parsing: prefers `__NEXT_DATA__` / Apollo state JSON; falls back to legacy HTML regex parsing.

## Local repo

- Path: `E:\repos\HUTContentSniffer`
- Main script: `sniff.py`
- Wrapper: `./sniff` (bash; uses `.venv/bin/python` when present)
- Config: `.env` (not in git; copy from `config.example.env`)
- Runtime state: `state.json` (not in git; tracks `last_seen_id`)
- Dependencies: `requirements.txt` (`curl_cffi`)

## Production (kapsi)

Deployed on **kapsi.fi**, user **bq**, host **lakka**.

SSH from this Windows machine — no password needed:

```bash
ssh kapsi
```

Configured in `C:\Users\micro\.ssh\config`:

```
Host kapsi
    HostName kapsi.fi
    User bq
    IdentityFile ~/.ssh/id_ed25519_kapsi
    IdentitiesOnly yes
```

Remote repo path:

```
/home/6/bq/HUTContentSniffer
```

(Also reachable as `~/HUTContentSniffer` when logged in as `bq`.)

### Cron

Runs once per hour at minute 12:

```cron
12 * * * * cd /home/6/bq/HUTContentSniffer && ./sniff >> sniff.log 2>&1
```

Check logs:

```bash
ssh kapsi "tail -20 ~/HUTContentSniffer/sniff.log"
```

### Python on kapsi

- Python 3.13, PEP 668 enforced — do **not** use `pip3 install --user`.
- Use repo-local venv: `~/HUTContentSniffer/.venv`
- `./sniff` auto-selects `.venv/bin/python` when it exists.
- After code changes: `git pull`, then ensure venv has deps:

```bash
ssh kapsi "cd ~/HUTContentSniffer && git pull && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
```

## Cloudflare / HTTP 403

Since ~2026-07-02, `forums.ea.com` blocks plain `urllib` and curl with HTTP 403 (Cloudflare TLS fingerprint check, `Cf-Mitigated: challenge`).

`sniff.py` uses `curl_cffi` with `impersonate="chrome"`. Without it, fetches fail with 403 regardless of User-Agent headers.

Test fetch from kapsi:

```bash
ssh kapsi "cd ~/HUTContentSniffer && ./sniff --dry-run --debug"
```

## Common tasks

| Task | Command |
|------|---------|
| Normal check (local) | `python sniff.py` or `./sniff` |
| Dry run, no email | `./sniff --dry-run` |
| Parse diagnostics | `./sniff --dry-run --debug` |
| Test SMTP only | `./sniff --test-email` |
| Reset baseline (no email) | `./sniff --init` |
| Deploy to kapsi | `ssh kapsi "cd ~/HUTContentSniffer && git pull"` |
| View cron | `ssh kapsi crontab -l` |

## Secrets and git

- **Never commit** `.env` or `state.json`.
- SMTP settings live in `.env` on kapsi only; do not read or echo them in logs.

## How to ask in a new chat

Short prompt that works well:

> HUTContentSniffer — read `AGENTS.md`. SSH to kapsi works via `ssh kapsi`. [describe task]

Examples:

- "Deploy latest main to kapsi and verify sniff.log"
- "Sniffer returns 403 again — diagnose and fix"
- "Add filter for post title X"

## GitHub

Remote: `https://github.com/Beeque/HUTContentSniffer` (branch `main`).

Only commit or push when the user explicitly asks.
