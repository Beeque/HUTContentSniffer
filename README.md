# HUTContentSniffer

Cron-friendly script that watches the EA NHL 26 HUT forum for new posts and sends email alerts.

Monitored page:

https://forums.ea.com/category/nhl-26-en/discussions/nhl-26-ultimate-team-en?messages.widget.messagelistfornodebyrecentactivitywidget-tab-main-sojpns-1=newest

## Setup

1. Copy config:

```bash
cp config.example.env .env
```

2. Edit `.env` with your email address and SMTP settings.

3. Initialize state (first run, no email):

```bash
python3 sniff.py --init
```

4. Optional: test email delivery:

```bash
python3 sniff.py --test-email
```

## Crontab

Example: check every 15 minutes.

```cron
*/15 * * * * cd /path/to/HUTContentSniffer && /usr/bin/python3 sniff.py >> sniff.log 2>&1
```

## How it works

- Fetches the forum page and parses post links from `<li class="...lia-panel-list-item...">` elements.
- Tracks the highest seen post id in `state.json`.
- Sends one email when new posts appear (with title + direct link for each new post).
- First run (`--init` or missing `state.json`) only stores current posts, no notification.

## CLI

```bash
python3 sniff.py            # normal check
python3 sniff.py --init     # reset baseline without email
python3 sniff.py --dry-run  # detect new posts, skip email
python3 sniff.py --test-email
```
