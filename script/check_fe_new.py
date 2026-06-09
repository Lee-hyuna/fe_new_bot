#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from datetime import datetime

GITHUB_API_URL = "https://api.github.com/repos/naver/fe-news/contents/issues"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/naver/fe-news/master/issues"
STATE_FILE = Path(__file__).parent.parent / "state" / "known_issues.json"
ISSUE_PATTERN = re.compile(r"^(\d{4})-(\d{2})\.md$")


def github_request(url, token=""):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "fe-news-notifier/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=30) as r:
        return json.loads(r.read().decode())


def fetch_raw_markdown(filename):
    url = f"{GITHUB_RAW_BASE}/{filename}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "fe-news-notifier/1.0"}), timeout=30) as r:
            return r.read().decode("utf-8")
    except Exception:
        return ""


def extract_preview(markdown, max_chars=350):
    lines = markdown.splitlines()
    preview_lines, char_count = [], 0
    for line in lines:
        s = line.strip()
        if re.match(r"# \d{4}-\d{2}", s) or (not s and not preview_lines):
            continue
        if s.startswith("## ") or s.startswith("- ") or s.startswith("* "):
            if char_count + len(s) > max_chars or len(preview_lines) >= 6:
                break
            preview_lines.append(s)
            char_count += len(s)
    return "\n".join(preview_lines)


def build_message(filename, html_url, preview):
    m = ISSUE_PATTERN.match(filename)
    year, month = m.group(1), m.group(2)
    title = f"{year}년 {month}월호"
    parts = [
        f'📰 <b>FE News {title}</b> 가 발행되었습니다!',
        '',
        f'🔗 <a href="{html_url}">바로 보기</a>',
    ]
    if preview:
        safe = preview.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        parts += ['', '📋 <b>미리보기</b>', f'<pre>{safe}</pre>']
    parts += ['', '—', 'naver/fe-news 월간 프론트엔드 뉴스레터']
    return "\n".join(parts)


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            result = json.loads(r.read().decode())
            if not result.get("ok"):
                print(f"[ERROR] Telegram API error: {result}", file=sys.stderr)
                return False
            return True
    except HTTPError as e:
        print(f"[ERROR] Telegram HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        return False
    except URLError as e:
        print(f"[ERROR] Telegram network error: {e}", file=sys.stderr)
        return False


def load_state():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("known_issues", []))
    return set()


def save_state(known):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({
            "known_issues": sorted(known),
            "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] State saved: {len(known)} known issues")


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()

    if not bot_token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Fetching file list from GitHub...")
    try:
        contents = github_request(GITHUB_API_URL, github_token)
    except HTTPError as e:
        print(f"[ERROR] GitHub API error {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"[ERROR] GitHub network error: {e}", file=sys.stderr)
        sys.exit(1)

    issue_files = {
        item["name"]: item
        for item in contents
        if isinstance(item, dict) and ISSUE_PATTERN.match(item.get("name", ""))
    }
    print(f"[INFO] Found {len(issue_files)} issue files on GitHub")

    known = load_state()
    print(f"[INFO] Known issues in state: {len(known)}")

    new_files = sorted(set(issue_files.keys()) - known)
    print(f"[INFO] New files: {new_files if new_files else 'none'}")

    if not new_files:
        print("[INFO] No new issues. Done.")
        return

    for filename in new_files:
        item = issue_files[filename]
        html_url = item.get(
            "html_url",
            f"https://github.com/naver/fe-news/blob/master/issues/{filename}",
        )
        preview = extract_preview(fetch_raw_markdown(filename))
        message = build_message(filename, html_url, preview)
        print(f"[INFO] Sending notification for: {filename}")
        if send_telegram(bot_token, chat_id, message):
            print(f"[OK] Notified: {filename}")
        else:
            print(f"[WARN] Notification failed for {filename}", file=sys.stderr)

    save_state(known | set(issue_files.keys()))


if __name__ == "__main__":
    main()
