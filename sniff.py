#!/usr/bin/env python3
"""Check EA NHL 26 HUT forum for new posts and send email alerts."""

import sys

if sys.version_info[0] < 3:
    sys.stderr.write("This script requires Python 3. Run: python3 sniff.py\n")
    sys.exit(1)
if sys.version_info < (3, 6):
    sys.stderr.write("HUTContentSniffer requires Python 3.6+. Run: python3 sniff.py\n")
    sys.exit(1)

import argparse
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

FORUM_URL = (
    "https://forums.ea.com/category/nhl-26-en/discussions/nhl-26-ultimate-team-en"
    "?messages.widget.messagelistfornodebyrecentactivitywidget-tab-main-sojpns-1=newest"
)
BASE_URL = "https://forums.ea.com"
FORUM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://forums.ea.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "state.json"
ENV_FILE = SCRIPT_DIR / ".env"
BOARD_SLUG = "nhl-26-ultimate-team-en"
COMMUNITY_MANAGER = "Community Manager"

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.S,
)
LI_RE = re.compile(r"<li[^>]*lia-panel-list-item[^>]*>([\s\S]*?)</li>", re.I)
POST_HREF_RE = re.compile(
    r'href="(/discussions/' + BOARD_SLUG + r'/[^"]+/(\d+))"', re.I
)
TITLE_RE = re.compile(
    r'data-testid="MessageSubject"[^>]*>.*?<a[^>]*>([\s\S]*?)</a>', re.I
)
COMMUNITY_MANAGER_RE = re.compile(
    r"(?:<span[^>]*>\s*Community Manager\s*</span>|Rank:\s*Community Manager)",
    re.I,
)


def log(message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sys.stdout.write("[{}] {}\n".format(ts, message))
    sys.stdout.flush()


def load_dotenv(path):
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


def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_state():
    if not STATE_FILE.is_file():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def strip_html(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def is_content_manager_post(chunk, title):
    if "Content" not in title:
        return False
    return bool(COMMUNITY_MANAGER_RE.search(chunk))


def extract_next_data(html):
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def author_rank_name(apollo_state, author):
    rank = author.get("rank", {})
    rank_ref = rank.get("__ref")
    if rank_ref:
        return apollo_state.get(rank_ref, {}).get("name", "")
    return rank.get("name", "")


def post_url_for_id(html, post_id):
    for href_match in POST_HREF_RE.finditer(html):
        if int(href_match.group(2)) == post_id:
            return "{}{}".format(BASE_URL, href_match.group(1))
    return "{}/discussions/{}/-/{}".format(BASE_URL, BOARD_SLUG, post_id)


def parse_posts_from_next_data(html):
    data = extract_next_data(html)
    if not data:
        return []

    apollo_state = data.get("props", {}).get("pageProps", {}).get("apolloState", {})
    if not apollo_state:
        return []

    posts = []
    seen_ids = set()
    for key, message in apollo_state.items():
        if not key.startswith("ForumTopicMessage:message:"):
            continue

        subject = message.get("subject", "")
        if "Content" not in subject:
            continue

        author_ref = message.get("author", {}).get("__ref")
        if not author_ref:
            continue
        author = apollo_state.get(author_ref, {})
        if author_rank_name(apollo_state, author) != COMMUNITY_MANAGER:
            continue

        post_id = int(message.get("uid") or key.rsplit(":", 1)[-1])
        if post_id in seen_ids:
            continue
        seen_ids.add(post_id)
        posts.append(
            {
                "id": post_id,
                "title": subject,
                "url": post_url_for_id(html, post_id),
            }
        )

    posts.sort(key=lambda post: post["id"], reverse=True)
    return posts


def parse_posts_legacy_html(html):
    posts = []
    seen_ids = set()

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
        if not is_content_manager_post(chunk, title):
            continue
        posts.append(
            {
                "id": post_id,
                "title": title,
                "url": "{}{}".format(BASE_URL, path),
            }
        )

    posts.sort(key=lambda post: post["id"], reverse=True)
    return posts


def debug_parse_stats(html):
    li_items = LI_RE.findall(html)
    href_matches = 0
    content_title_matches = 0
    manager_matches = 0

    for chunk in li_items:
        if not POST_HREF_RE.search(chunk):
            continue
        href_matches += 1
        title_match = TITLE_RE.search(chunk)
        title = strip_html(title_match.group(1)) if title_match else ""
        if "Content" in title:
            content_title_matches += 1
        if COMMUNITY_MANAGER_RE.search(chunk):
            manager_matches += 1

    next_data = extract_next_data(html)
    next_posts = parse_posts_from_next_data(html) if next_data else []
    page_props = (
        next_data.get("props", {}).get("pageProps", {}) if next_data else {}
    )

    log("Debug: html_bytes={}".format(len(html)))
    log("Debug: next_data={}".format("yes" if next_data else "no"))
    log("Debug: forum_topic_messages_in_html={}".format(
        html.count("ForumTopicMessage:message:")
    ))
    if page_props:
        log("Debug: is_crawler={}".format(page_props.get("isCrawler")))
    log("Debug: next_data_matching_posts={}".format(len(next_posts)))
    log("Debug: panel_list_items={}".format(len(li_items)))
    log("Debug: hut_posts={}".format(href_matches))
    log("Debug: title_has_Content={}".format(content_title_matches))
    log("Debug: community_manager={}".format(manager_matches))
    if "cf-browser-verification" in html or "security verification" in html.lower():
        log("Debug: page looks like a Cloudflare challenge, not forum HTML")
    elif next_data and not next_posts and html.count("ForumTopicMessage:message:") == 0:
        log("Hint: EA returned a shell page without embedded posts (common on datacenter IPs).")


def looks_like_cloudflare_challenge(html):
    lowered = html.lower()
    return "cf-browser-verification" in html or "security verification" in lowered


def parse_posts(html):
    posts = parse_posts_from_next_data(html)
    if posts:
        return posts
    return parse_posts_legacy_html(html)


IMPERSONATE_PROFILES = (
    "chrome124",
    "safari17_0",
    "chrome131",
    "chrome120",
    "chrome",
)


def fetch_forum_html():
    # Cloudflare on forums.ea.com fingerprints the client TLS handshake
    # (JA3/JA4), so plain urllib gets HTTP 403 regardless of headers.
    # curl_cffi impersonates a real Chrome TLS+HTTP/2 fingerprint.
    # Datacenter IPs may only pass with specific profiles; try fallbacks.
    if curl_requests is not None:
        last_status = None
        for profile in IMPERSONATE_PROFILES:
            response = curl_requests.get(
                FORUM_URL, impersonate=profile, timeout=45
            )
            last_status = response.status_code
            if response.status_code == 200:
                if profile != IMPERSONATE_PROFILES[0]:
                    log("Fetched forum page using impersonate={}".format(profile))
                return response.text
        raise URLError(
            "HTTP {} from forum (Cloudflare challenge?)".format(last_status)
        )

    log("Warning: curl_cffi not installed, falling back to urllib "
        "(likely to be blocked by Cloudflare). Run: pip3 install --user curl_cffi")
    request = Request(FORUM_URL, headers=FORUM_HEADERS)
    with urlopen(request, timeout=45) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def send_email(posts, test_mode=False):
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
        raise RuntimeError("Missing email config: {}".format(", ".join(missing)))

    if test_mode:
        subject = "HUTContentSniffer test email"
    elif len(posts) == 1:
        subject = "EA HUT Content: {}".format(posts[0]["title"])
    else:
        subject = "EA HUT Content: {} new posts".format(len(posts))

    if test_mode:
        lines = [
            "This is a test message from HUTContentSniffer.",
            "",
            "SMTP settings look OK.",
            "",
            "Monitored forum:",
            FORUM_URL,
        ]
    else:
        lines = [
            "New HUT Content post(s) on EA forum:",
            "",
            FORUM_URL,
            "",
        ]
        for post in posts:
            lines.append("- {}".format(post["title"]))
            lines.append("  {}".format(post["url"]))
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


def run(init_only=False, test_email=False, dry_run=False, debug=False):
    load_dotenv(ENV_FILE)

    if test_email:
        log("Sending test email to {} via {}".format(
            env("NOTIFY_EMAIL", "(not set)"),
            env("SMTP_HOST", "(not set)"),
        ))
        try:
            send_email([], test_mode=True)
            log("Test email sent.")
            return 0
        except Exception as exc:
            log("Test email failed: {}".format(exc))
            return 1

    try:
        html = fetch_forum_html()
    except HTTPError as exc:
        if exc.code == 403:
            log("Failed to fetch forum page: HTTP 403 (Cloudflare bot check). "
                "Install curl_cffi: pip3 install --user curl_cffi")
        else:
            log("Failed to fetch forum page: {}".format(exc))
        return 1
    except (URLError, OSError) as exc:
        log("Failed to fetch forum page: {}".format(exc))
        return 1
    except Exception as exc:
        # curl_cffi raises its own exception types on network errors.
        log("Failed to fetch forum page: {}: {}".format(type(exc).__name__, exc))
        return 1

    posts = parse_posts(html)
    if not posts:
        log("No matching Content posts from Community Manager found.")
        debug_parse_stats(html)
        if looks_like_cloudflare_challenge(html):
            log("Hint: received Cloudflare bot-check page instead of forum content.")
        return 1

    newest_id = posts[0]["id"]
    state = load_state()
    last_seen_id = int(state.get("last_seen_id", 0))
    new_posts = [post for post in posts if post["id"] > last_seen_id]
    new_posts.sort(key=lambda post: post["id"])

    log(
        "Fetched {} matching posts, newest id={}, last_seen_id={}".format(
            len(posts), newest_id, last_seen_id
        )
    )

    if not state or init_only:
        save_state(
            {
                "last_seen_id": newest_id,
                "initialized_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        log("Initialized state at post id={} (no notifications sent).".format(newest_id))
        return 0

    if new_posts:
        log("Found {} new Content post(s).".format(len(new_posts)))
        for post in new_posts:
            log("  [{}] {}".format(post["id"], post["title"]))
        if dry_run:
            log("Dry run: email not sent.")
        else:
            send_email(new_posts)
            log("Notification email sent.")
    else:
        log("No new Content posts.")

    if not dry_run:
        save_state(
            {
                "last_seen_id": max(newest_id, last_seen_id),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize state from current forum posts without sending email.",
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send a test email to verify SMTP settings (does not use forum data).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect new posts but do not send email.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print parse diagnostics when no matching posts are found.",
    )
    args = parser.parse_args()
    return run(
        init_only=args.init,
        test_email=args.test_email,
        dry_run=args.dry_run,
        debug=args.debug,
    )


if __name__ == "__main__":
    sys.exit(main())
