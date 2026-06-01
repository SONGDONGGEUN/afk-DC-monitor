from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from http_utils import with_retry

CAFE_URL_NAME = "afkjourneykr"
CAFE_ID = "30996029"

LIST_API = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
READ_API = f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{CAFE_ID}/articles/{{}}"
ARTICLE_URL = f"https://cafe.naver.com/{CAFE_URL_NAME}/{{}}"

HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": f"https://cafe.naver.com/{CAFE_URL_NAME}",
    "X-Cafe-Product": "pc",
    "Origin": "https://cafe.naver.com",
}


@dataclass
class Article:
    id: int
    menu_id: int
    menu_name: str
    subject: str
    writer: str
    datetime: str  # human readable
    url: str
    views: int
    comments: int


class NaverAuthError(RuntimeError):
    """Raised when the Naver cookie no longer grants member access."""


def _make_session(cookie: str) -> requests.Session:
    s = requests.Session()
    headers = dict(HEADERS_BASE)
    headers["Cookie"] = cookie
    s.headers.update(headers)
    return s


def _ts_to_str(ts_ms: int | None) -> str:
    if not ts_ms:
        return "?"
    try:
        return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


def fetch_articles(
    cookie: str,
    menu_id: int,
    per_page: int = 20,
    timeout: int = 30,
) -> tuple[list[Article], bool]:
    """Fetch latest articles in a single board.

    Returns (articles, is_member). is_member=False means the cookie likely
    expired and we are seeing only public content (or none).
    """
    s = _make_session(cookie)
    params = {
        "search.clubid": CAFE_ID,
        "search.menuid": menu_id,
        "search.queryType": "lastArticle",
        "search.page": 1,
        "search.perPage": per_page,
    }

    def _do():
        rr = s.get(LIST_API, params=params, timeout=timeout)
        rr.raise_for_status()
        return rr

    r = with_retry(_do, label=f"naver.fetch_articles(menu={menu_id})")
    j = r.json()
    msg = j.get("message", {})
    if msg.get("status") != "200":
        err = msg.get("error", {})
        raise RuntimeError(f"Naver list API error: {err}")

    result = msg.get("result", {})
    is_member = bool(result.get("cafeMember"))
    raw_list = result.get("articleList") or []

    articles: list[Article] = []
    for a in raw_list:
        aid = a.get("articleId")
        if not aid:
            continue
        articles.append(
            Article(
                id=int(aid),
                menu_id=int(a.get("menuId") or menu_id),
                menu_name=str(a.get("menuName") or ""),
                subject=str(a.get("subject") or ""),
                writer=str(a.get("writerNickname") or "?"),
                datetime=_ts_to_str(a.get("writeDateTimestamp")),
                url=ARTICLE_URL.format(aid),
                views=int(a.get("readCount") or 0),
                comments=int(a.get("commentCount") or 0),
            )
        )
    return articles, is_member


def fetch_article_body(cookie: str, article_id: int, timeout: int = 20) -> str:
    """Fetch and return plain-text body of a single article."""
    s = _make_session(cookie)
    s.headers["Referer"] = ARTICLE_URL.format(article_id)
    r = s.get(READ_API.format(article_id), timeout=timeout)
    r.raise_for_status()
    j = r.json()
    article = (j.get("result") or {}).get("article") or {}
    if article.get("isBlind") or not article.get("isReadable", True):
        return ""
    html = article.get("contentHtml") or ""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(" ", strip=True)


def is_notice_article(art_id: int, cookie: str) -> bool:
    """Convenience: check single article's isNotice flag. Rarely needed because
    we filter notices upstream via menu selection and per-article isNotice in body."""
    try:
        s = _make_session(cookie)
        r = s.get(READ_API.format(art_id), timeout=10)
        article = (r.json().get("result") or {}).get("article") or {}
        return bool(article.get("isNotice"))
    except Exception:
        return False
