#!/usr/bin/env python3
"""Check EA NHL 26 HUT forum for new posts and send email alerts."""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

FORUM_URL = (
    "https://forums.ea.com/category/nhl-26-en/discussions/nhl-26-ultimate-team-en"
    "?messages.widget.messagelistfornodebyrecentactivitywidget-tab-main-sojpns-1=newest"
)
BASE_URL = "https://forums.ea.com"
USER_AGENT = "HUTContentSniffer/1.0 (+https://github.com/Beeque/HUTContentSniffer)"

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "state.json"
ENV_FILE = SCRIPT_DIR / ".env"

LI_RE = re.compile(r"<li[^>]*lia-panel-list-item[^>]*>([\s\S]*?)</li>", re.I)
POST_HREF_RE = re.compile(
    r'href="(/discussions/nhl-26-ultimate-team-en/[^"]+/(\d+))"', re.I
)
TITLE_RE = re.compile(
    r'data-testid="MessageSubject"[^>]*>.*?<a[^>]*>([\s\S]*?)</a>', re.I
)


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {message}", flush=True)


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def fetch_forum_html() -> str:
    request = Request(
        FORUM_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=45) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_posts(html: str) -> list[dict]:
    posts: list[dict] = []
    seen_ids: set[int] = set()

    for match in LI_RE.finditer(html):
        chunk = match.group(1)
        href_match = POST_HREF_RE.search(chunk)
        if not href_match:
            continue

        path = href_match.group(1)
        post_id = int(href_match.group(2))
        if post_id in seen_ids:
            continue
        seen_ids.add(post_id)

        title_match = TITLE_RE.search(chunk)
        title = strip_html(title_match.group(1)) if title_match else path.rsplit("/", 2)[-2]
        posts.append(
            {
                "id": post_id,
                "title": title,
                "url": f"{BASE_URL}{path}",
            }
        )

    posts.sort(key=lambda post: post["id"], reverse=True)
    return posts


def send_email(posts: list[dict]) -> None:
    notify_to = env("NOTIFY_EMAIL")
    smtp_host = env("SMTP_HOST")
    smtp_port = int(env("SMTP_PORT", "587"))
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASS")
    smtp_from = env("SMTP_FROM", smtp_user)
    use_tls = env("SMTP_TLS", "1") != "0"

    missing = [
        name
        for name, value in [
            ("NOTIFY_EMAIL", notify_to),
            ("SMTP_HOST", smtp_host),
            ("SMTP_USER", smtp_user),
            ("SMTP_PASS", smtp_pass),
            ("SMTP_FROM", smtp_from),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing email config: {', '.join(missing)}")

    if len(posts) == 1:
        subject = f"EA HUT forum: {posts[0]['title']}"
    else:
        subject = f"EA HUT forum: {len(posts)} new posts"

    lines = [
        "New post(s) on EA NHL 26 HUT forum:",
        "",
        FORUM_URL,
        "",
    ]
    for post in posts:
        lines.append(f"- {post['title']}")
        lines.append(f"  {post['url']}")
        lines.append("")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = notify_to
    message.set_content("\n".join(lines).strip())

    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(smtp_user, smtp_pass)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            if smtp_user and smtp_pass:
                smtp.login(smtp_user, smtp_pass)
            smtp.send_message(message)


def run(*, init_only: bool, test_email: bool, dry_run: bool) -> int:
    load_dotenv(ENV_FILE)

    try:
        html = fetch_forum_html()
    except URLError as exc:
        log(f"Failed to fetch forum page: {exc}")
        return 1

    posts = parse_posts(html)
    if not posts:
        log("No posts found on forum page (HTML structure may have changed).")
        return 1

    newest_id = posts[0]["id"]
    state = load_state()
    last_seen_id = int(state.get("last_seen_id", 0))
    new_posts = [post for post in posts if post["id"] > last_seen_id]
    new_posts.sort(key=lambda post: post["id"])

    log(f"Fetched {len(posts)} posts, newest id={newest_id}, last_seen_id={last_seen_id}")

    if test_email:
        sample = new_posts or posts[:1]
        log(f"Sending test email about: {sample[0]['title']}")
        send_email(sample)
        log("Test email sent.")
        return 0

    if not state or init_only:
        save_state(
            {
                "last_seen_id": newest_id,
                "initialized_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        log(f"Initialized state at post id={newest_id} (no notifications sent).")
        return 0

    if new_posts:
        log(f"Found {len(new_posts)} new post(s).")
        for post in new_posts:
            log(f"  [{post['id']}] {post['title']}")
        if dry_run:
            log("Dry run: email not sent.")
        else:
            send_email(new_posts)
            log("Notification email sent.")
    else:
        log("No new posts.")

    save_state(
        {
            "last_seen_id": max(newest_id, last_seen_id),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize state from current forum posts without sending email.",
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send one test email using current/newest post as sample content.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect new posts but do not send email.",
    )
    args = parser.parse_args()
    return run(init_only=args.init, test_email=args.test_email, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
