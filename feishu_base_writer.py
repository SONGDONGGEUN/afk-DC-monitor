from __future__ import annotations

import sys
import time
import requests
from datetime import datetime

BASE_TOKEN = "S8sKbbChsanrhIsX4czcVs6OnQb"
TABLE_ID = "tblLBlUStdgwFxZF"
VERSION = "V171"

NEGATIVE_WORDS = [
    "오역", "이상해", "이상한", "이상함", "어색", "직역",
    "버그", "오류", "잘못", "안타깝", "실망", "최악", "별로",
    "불만", "이상하다", "번역 문제", "번역이 별로", "번역 이상",
]
POSITIVE_WORDS = [
    "좋아", "훌륭", "잘했", "최고", "감동", "완벽", "멋있",
    "잘 번역", "번역 잘", "번역이 좋",
]

KEYWORD_TO_TYPE: dict[str, str] = {
    "번역":   "翻译/번역",
    "현지화": "翻译/번역",
    "직역":   "翻译/번역",
    "어색":   "翻译/번역",
    "오역":   "翻译/번역",
    "언어":   "翻译/번역",
    "중국어": "翻译/번역",
    "한국어": "翻译/번역",
    "스토리": "剧情/스토리",
    "대사":   "剧情/스토리",
    "버그":   "其他/기타",
    "오류":   "其他/기타",
}


def classify_sentiment(title: str, body: str = "") -> str:
    text = (title + " " + body).lower()
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    if neg > pos:
        return "负面/부정적"
    if pos > 0:
        return "正面/긍정적"
    return "中性/중성적"


def keywords_to_types(matched_keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    types: list[str] = []
    for kw in matched_keywords:
        t = KEYWORD_TO_TYPE.get(kw)
        if t and t not in seen:
            seen.add(t)
            types.append(t)
    return types if types else ["其他/기타"]


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"failed to get token: {data}")
    return token


def _dt_to_ms(dt_str: str) -> int:
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(dt_str.strip(), fmt).timestamp() * 1000)
        except ValueError:
            continue
    return int(time.time() * 1000)


def create_record(
    app_id: str,
    app_secret: str,
    *,
    title: str,
    url: str,
    dt_str: str,
    source: str,
    matched_keywords: list[str],
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    body: str = "",
) -> bool:
    community = "DC Inside" if source == "dc" else "Naver Cafe"
    fields: dict = {
        "简单描述内容": title,
        "链接": url,
        "反馈日期": _dt_to_ms(dt_str),
        "社群": community,
        "反馈类型": keywords_to_types(matched_keywords),
        "版本": VERSION,
        "性质": classify_sentiment(title, body),
        "浏览": views,
        "点赞": likes,
        "评论": comments,
    }
    try:
        token = _get_tenant_token(app_id, app_secret)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        api_url = (
            f"https://open.feishu.cn/open-apis/bitable/v1"
            f"/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records"
        )
        r = requests.post(api_url, headers=headers, json={"fields": fields}, timeout=15)
        r.raise_for_status()
        resp = r.json()
        if resp.get("code") != 0:
            print(f"[base] API error: {resp}", file=sys.stderr)
            return False
        print(f"[base] record created: {title[:50]}")
        return True
    except Exception as e:
        print(f"[base] create_record FAIL: {e}", file=sys.stderr)
        return False
