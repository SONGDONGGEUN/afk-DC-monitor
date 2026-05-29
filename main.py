from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dc_scraper import fetch_posts, fetch_post_body, Post
from naver_scraper import (
    fetch_articles as naver_fetch_articles,
    fetch_article_body as naver_fetch_body,
    Article,
)
from feishu_sender import send_card

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
KEYWORDS_FILE = ROOT / "keywords.txt"
KEYWORDS_BODY_FILE = ROOT / "keywords_body.txt"
NAVER_MENUS_FILE = ROOT / "naver_menus.txt"

MAX_ALERTS_PER_RUN = 20
BODY_FETCH_DELAY_SEC = 0.5
NAVER_PER_PAGE = 20


def _load_keyword_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def load_keywords() -> list[str]:
    return _load_keyword_file(KEYWORDS_FILE)


def load_body_keywords() -> list[str]:
    return _load_keyword_file(KEYWORDS_BODY_FILE)


def load_naver_menus() -> list[tuple[int, str]]:
    if not NAVER_MENUS_FILE.exists():
        return []
    menus: list[tuple[int, str]] = []
    for ln in NAVER_MENUS_FILE.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        mid = int(parts[0])
        name = parts[1] if len(parts) > 1 else f"menu{mid}"
        menus.append((mid, name))
    return menus


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"dc": {"last_seen_no": 0}, "naver": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"dc": {"last_seen_no": 0}, "naver": {}}
    # migrate legacy flat schema
    if "dc" not in data and "last_seen_no" in data:
        data = {"dc": {"last_seen_no": data["last_seen_no"]}, "naver": {}}
    data.setdefault("dc", {"last_seen_no": 0})
    data.setdefault("naver", {})
    return data


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    t = text.lower()
    return [k for k in keywords if k.lower() in t]


def _process_dc(
    state: dict,
    keywords: list[str],
    body_keywords: list[str],
    webhook: str,
    secret: str | None,
    sent_counter: dict,
) -> None:
    print("\n[dc] start")
    last_seen = int(state["dc"].get("last_seen_no", 0))
    try:
        posts = fetch_posts()
    except Exception as e:
        print(f"[dc] ERROR fetching: {e}", file=sys.stderr)
        sent_counter["errors"] += 1
        return
    if not posts:
        print("[dc] no posts returned")
        return

    posts_sorted = sorted(posts, key=lambda p: p.no)
    highest_no = posts_sorted[-1].no

    if last_seen == 0:
        state["dc"]["last_seen_no"] = highest_no
        print(f"[dc] baseline set to no={highest_no}, no alerts sent")
        return

    new_posts = [p for p in posts_sorted if p.no > last_seen]
    print(f"[dc] last_seen={last_seen} new={len(new_posts)}")

    matched: list[tuple[Post, list[str], str]] = []
    body_fetches = body_errors = 0
    for p in new_posts:
        mk = match_keywords(p.title, keywords)
        if mk:
            matched.append((p, mk, "title"))
            continue
        if not body_keywords:
            continue
        try:
            time.sleep(BODY_FETCH_DELAY_SEC)
            body = fetch_post_body(p.url)
            body_fetches += 1
            bk = match_keywords(body, body_keywords)
            if bk:
                matched.append((p, bk, "body"))
        except Exception as e:
            body_errors += 1
            print(f"  [dc] body-fetch FAIL [{p.no}]: {e}", file=sys.stderr)

    print(f"[dc] matched={len(matched)} body_fetches={body_fetches} body_errors={body_errors}")

    for p, mk, where in matched[: MAX_ALERTS_PER_RUN - sent_counter["sent"]]:
        try:
            send_card(
                webhook,
                secret,
                title=p.title,
                author=p.author,
                dt=p.datetime,
                url=p.url,
                matched_keywords=mk,
                matched_in=where,
                source="dc",
            )
            sent_counter["sent"] += 1
            print(f"  [dc] sent [{p.no}] in={where} matched={mk}")
        except Exception as e:
            sent_counter["errors"] += 1
            print(f"  [dc] send FAIL [{p.no}]: {e}", file=sys.stderr)

    state["dc"]["last_seen_no"] = highest_no


def _process_naver(
    state: dict,
    keywords: list[str],
    body_keywords: list[str],
    webhook: str,
    secret: str | None,
    sent_counter: dict,
) -> None:
    cookie = os.environ.get("NAVER_COOKIE", "").strip()
    if not cookie:
        print("\n[naver] NAVER_COOKIE not set, skipping Naver Cafe")
        return

    menus = load_naver_menus()
    if not menus:
        print("\n[naver] no menus configured, skipping")
        return

    print(f"\n[naver] start (menus: {len(menus)})")

    for menu_id, menu_name in menus:
        if sent_counter["sent"] >= MAX_ALERTS_PER_RUN:
            print(f"[naver] alert cap reached, skipping remaining menus")
            break

        menu_state = state["naver"].setdefault(
            str(menu_id), {"last_seen_id": 0}
        )
        last_seen = int(menu_state.get("last_seen_id", 0))

        try:
            articles, is_member = naver_fetch_articles(
                cookie, menu_id, per_page=NAVER_PER_PAGE
            )
        except Exception as e:
            print(f"[naver:{menu_id} {menu_name}] fetch FAIL: {e}", file=sys.stderr)
            sent_counter["errors"] += 1
            continue

        if not is_member:
            print(
                f"[naver:{menu_id} {menu_name}] WARN: cafeMember=False -- "
                "cookie likely expired; refresh NAVER_COOKIE secret",
                file=sys.stderr,
            )
            sent_counter["errors"] += 1
            # don't bail entirely; still process whatever (likely empty) result

        if not articles:
            print(f"[naver:{menu_id} {menu_name}] no articles returned")
            continue

        articles_sorted = sorted(articles, key=lambda a: a.id)
        highest_id = articles_sorted[-1].id

        if last_seen == 0:
            menu_state["last_seen_id"] = highest_id
            print(f"[naver:{menu_id} {menu_name}] baseline set to id={highest_id}")
            continue

        new_arts = [a for a in articles_sorted if a.id > last_seen]
        print(
            f"[naver:{menu_id} {menu_name}] last_seen={last_seen} new={len(new_arts)}"
        )

        matched: list[tuple[Article, list[str], str]] = []
        body_fetches = body_errors = 0
        for a in new_arts:
            mk = match_keywords(a.subject, keywords)
            if mk:
                matched.append((a, mk, "title"))
                continue
            if not body_keywords:
                continue
            try:
                time.sleep(BODY_FETCH_DELAY_SEC)
                body = naver_fetch_body(cookie, a.id)
                body_fetches += 1
                bk = match_keywords(body, body_keywords)
                if bk:
                    matched.append((a, bk, "body"))
            except Exception as e:
                body_errors += 1
                print(
                    f"  [naver:{menu_id}] body-fetch FAIL [{a.id}]: {e}",
                    file=sys.stderr,
                )

        print(
            f"[naver:{menu_id} {menu_name}] matched={len(matched)} "
            f"body_fetches={body_fetches} body_errors={body_errors}"
        )

        for a, mk, where in matched[: MAX_ALERTS_PER_RUN - sent_counter["sent"]]:
            try:
                send_card(
                    webhook,
                    secret,
                    title=a.subject,
                    author=a.writer,
                    dt=a.datetime,
                    url=a.url,
                    matched_keywords=mk,
                    matched_in=where,
                    source="naver",
                    board=menu_name,
                )
                sent_counter["sent"] += 1
                print(f"  [naver:{menu_id}] sent [{a.id}] in={where} matched={mk}")
            except Exception as e:
                sent_counter["errors"] += 1
                print(
                    f"  [naver:{menu_id}] send FAIL [{a.id}]: {e}", file=sys.stderr
                )

        menu_state["last_seen_id"] = highest_id


def main() -> int:
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    secret = os.environ.get("FEISHU_SECRET", "").strip() or None
    if not webhook:
        print("ERROR: FEISHU_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    keywords = load_keywords()
    body_keywords = load_body_keywords()
    state = load_state()

    print(f"[run] title keywords ({len(keywords)}): {keywords}")
    print(f"[run] body  keywords ({len(body_keywords)}): {body_keywords}")

    sent_counter = {"sent": 0, "errors": 0}

    _process_dc(state, keywords, body_keywords, webhook, secret, sent_counter)
    _process_naver(state, keywords, body_keywords, webhook, secret, sent_counter)

    save_state(state)

    print(
        f"\n[run] done. total_sent={sent_counter['sent']} "
        f"errors={sent_counter['errors']}"
    )
    return 0 if sent_counter["errors"] == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
