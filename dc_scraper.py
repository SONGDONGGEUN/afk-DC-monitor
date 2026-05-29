from __future__ import annotations

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass

GALLERY_ID = "newafk"
LIST_URL = f"https://gall.dcinside.com/mgallery/board/lists?id={GALLERY_ID}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://gall.dcinside.com/",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


@dataclass
class Post:
    no: int
    title: str
    author: str
    datetime: str
    url: str
    views: int
    recommends: int


def fetch_post_body(url: str, timeout: int = 10) -> str:
    """Fetch and return the plain text body of a single DC post."""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "lxml", from_encoding="utf-8")
    body = soup.select_one("div.write_div")
    return body.get_text(" ", strip=True) if body else ""


def fetch_posts(timeout: int = 15) -> list[Post]:
    r = requests.get(LIST_URL, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "lxml", from_encoding="utf-8")

    posts: list[Post] = []
    for tr in soup.select("tr.ub-content.us-post[data-no]"):
        dtype = tr.get("data-type") or ""
        if "notice" in dtype:
            continue

        no_str = tr.get("data-no") or ""
        if not no_str.isdigit():
            continue
        no = int(no_str)

        tit_a = tr.select_one("td.gall_tit a")
        if not tit_a:
            continue
        title = tit_a.get_text(strip=True)
        href = tit_a.get("href") or ""
        url = f"https://gall.dcinside.com{href}" if href.startswith("/") else href

        writer_td = tr.select_one("td.gall_writer")
        author = (writer_td.get("data-nick") if writer_td else "") or "?"

        date_td = tr.select_one("td.gall_date")
        dt_full = (date_td.get("title") if date_td else "") or (
            date_td.get_text(strip=True) if date_td else ""
        )

        def to_int(td_sel: str) -> int:
            td = tr.select_one(td_sel)
            if not td:
                return 0
            txt = td.get_text(strip=True).replace(",", "")
            return int(txt) if txt.isdigit() else 0

        posts.append(
            Post(
                no=no,
                title=title,
                author=author,
                datetime=dt_full,
                url=url,
                views=to_int("td.gall_count"),
                recommends=to_int("td.gall_recommend"),
            )
        )
    return posts
