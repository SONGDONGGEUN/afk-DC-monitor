from __future__ import annotations

import base64
import hashlib
import hmac
import time
import requests


_SOURCE_LABELS: dict[str, str] = {
    "dc": "DC 뉴afk",
    "naver": "네이버 카페",
}
_SOURCE_TEMPLATES: dict[str, str] = {
    "dc": "blue",
    "naver": "green",
}


def _make_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    h = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(h).decode("utf-8")


def _build_card(
    title: str,
    author: str,
    dt: str,
    url: str,
    matched_keywords: list[str],
    matched_in: str = "title",
    source: str = "dc",
    board: str | None = None,
) -> dict:
    kw_str = ", ".join(f"`{k}`" for k in matched_keywords) if matched_keywords else "-"
    where_label = "본문" if matched_in == "body" else "제목"
    template = _SOURCE_TEMPLATES.get(source, "blue")
    source_label = _SOURCE_LABELS.get(source, source.upper())

    header_parts = [source_label]
    if board:
        header_parts.append(board)
    header_parts.append(f"{where_label} 매칭")
    header_suffix = " · ".join(header_parts)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🔔 AFK 새 글 알림 ({header_suffix})",
            },
            "template": template,
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{title}**",
                },
            },
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**작성자**\n{author}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**시간**\n{dt}",
                        },
                    },
                    {
                        "is_short": False,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**매칭 키워드 ({where_label})**\n{kw_str}",
                        },
                    },
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "🔗 글 보러가기",
                        },
                        "url": url,
                        "type": "primary",
                    }
                ],
            },
        ],
    }


def send_card(
    webhook_url: str,
    secret: str | None,
    *,
    title: str,
    author: str,
    dt: str,
    url: str,
    matched_keywords: list[str],
    matched_in: str = "title",
    source: str = "dc",
    board: str | None = None,
    timeout: int = 10,
) -> dict:
    payload: dict = {
        "msg_type": "interactive",
        "card": _build_card(
            title, author, dt, url, matched_keywords, matched_in, source, board
        ),
    }
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _make_signature(ts, secret)

    r = requests.post(webhook_url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def send_text(
    webhook_url: str, secret: str | None, text: str, timeout: int = 10
) -> dict:
    payload: dict = {"msg_type": "text", "content": {"text": text}}
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _make_signature(ts, secret)
    r = requests.post(webhook_url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()
