"""Send a Feishu alert when the monitor workflow fails.

Uses only Python stdlib so it still works if `pip install` itself failed.
Invoked from the GitHub Actions workflow with `if: failure()`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request


def make_sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    h = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(h).decode("utf-8")


def main() -> int:
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    secret = os.environ.get("FEISHU_SECRET", "").strip() or None
    if not webhook:
        print("WARN: FEISHU_WEBHOOK_URL not set, skipping failure notification", file=sys.stderr)
        return 0

    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "?/?")
    run_id = os.environ.get("GITHUB_RUN_ID", "0")
    workflow = os.environ.get("GITHUB_WORKFLOW", "AFK Monitor")
    run_url = f"{server}/{repo}/actions/runs/{run_id}"

    payload: dict = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "⚠️ AFK Monitor 실행 실패",
                },
                "template": "red",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "GitHub Actions 워크플로 실행 중 에러가 발생했습니다.\n"
                            "아래 버튼으로 로그 확인 후, 필요하면 Claude에게 문의해주세요."
                        ),
                    },
                },
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**Workflow**\n{workflow}",
                            },
                        },
                        {
                            "is_short": True,
                            "text": {
                                "tag": "lark_md",
                                "content": f"**Run ID**\n{run_id}",
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
                                "content": "🔗 로그 확인하기",
                            },
                            "url": run_url,
                            "type": "danger",
                        }
                    ],
                },
            ],
        },
    }

    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = make_sign(ts, secret)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print("failure notification sent:", r.read().decode("utf-8"))
    except Exception as e:
        print(f"FAIL to send failure notification: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
