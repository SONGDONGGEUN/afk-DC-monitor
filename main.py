from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dc_scraper import fetch_posts, Post
from feishu_sender import send_card

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
KEYWORDS_FILE = ROOT / "keywords.txt"

MAX_ALERTS_PER_RUN = 10


def load_keywords() -> list[str]:
    if not KEYWORDS_FILE.exists():
        return []
    return [
        ln.strip()
        for ln in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_seen_no": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_seen_no": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def match_keywords(title: str, keywords: list[str]) -> list[str]:
    t = title.lower()
    return [k for k in keywords if k.lower() in t]


def main() -> int:
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    secret = os.environ.get("FEISHU_SECRET", "").strip() or None
    if not webhook:
        print("ERROR: FEISHU_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    keywords = load_keywords()
    if not keywords:
        print("WARN: no keywords loaded; nothing will match", file=sys.stderr)

    state = load_state()
    last_seen = int(state.get("last_seen_no", 0))

    print(f"[run] last_seen_no={last_seen} | keywords={keywords}")

    try:
        posts = fetch_posts()
    except Exception as e:
        print(f"ERROR fetching DC: {e}", file=sys.stderr)
        return 2

    if not posts:
        print("[run] no posts returned")
        return 0

    posts_sorted = sorted(posts, key=lambda p: p.no)
    highest_no = posts_sorted[-1].no

    if last_seen == 0:
        save_state({"last_seen_no": highest_no})
        print(f"[run] first run: baseline set to no={highest_no}, no alerts sent")
        return 0

    new_posts = [p for p in posts_sorted if p.no > last_seen]
    print(f"[run] {len(new_posts)} new posts since last run")

    matched: list[tuple[Post, list[str]]] = []
    for p in new_posts:
        mk = match_keywords(p.title, keywords)
        if mk:
            matched.append((p, mk))

    print(f"[run] {len(matched)} matched keywords")

    sent = 0
    errors = 0
    for p, mk in matched[:MAX_ALERTS_PER_RUN]:
        try:
            send_card(
                webhook,
                secret,
                title=p.title,
                author=p.author,
                dt=p.datetime,
                url=p.url,
                matched_keywords=mk,
            )
            sent += 1
            print(f"  sent: [{p.no}] {p.title[:50]} | matched={mk}")
        except Exception as e:
            errors += 1
            print(f"  FAIL: [{p.no}] {e}", file=sys.stderr)

    if len(matched) > MAX_ALERTS_PER_RUN:
        skipped = len(matched) - MAX_ALERTS_PER_RUN
        print(f"[run] WARN: {skipped} matches truncated (cap={MAX_ALERTS_PER_RUN})")

    save_state({"last_seen_no": highest_no})
    print(f"[run] done. sent={sent} errors={errors} new_last_seen={highest_no}")
    return 0 if errors == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
