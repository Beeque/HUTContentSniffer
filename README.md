# HUTContentSniffer

Cron-friendly script that watches the EA NHL 26 HUT forum for new posts and sends email alerts.

Monitored page:

https://forums.ea.com/category/nhl-26-en/discussions/nhl-26-ultimate-team-en?messages.widget.messagelistfornodebyrecentactivitywidget-tab-main-sojpns-1=newest

## Requirements

Python **3.6+**. On Linux, **`python` is often Python 2** — do not use it.

```bash
python3 --version
chmod +x sniff
./sniff --init
```

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
*/15 * * * * cd /home/bq/HUTContentSniffer && ./sniff >> sniff.log 2>&1
```

## How it works

- Fetches the forum page and parses post links from `<li class="...lia-panel-list-item...">` elements.
- Keeps only posts where the title contains **Content** and the author rank is **Community Manager**.
- Tracks the highest seen matching post id in `state.json`.
- Sends one email when new matching posts appear (with title + direct link for each).
- First run (`--init` or missing `state.json`) only stores current matching posts, no notification.

## CLI

```bash
python3 sniff.py            # normal check
python3 sniff.py --init     # reset baseline without email
python3 sniff.py --dry-run  # detect new posts, skip email
python3 sniff.py --test-email
```
