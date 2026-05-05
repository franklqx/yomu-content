"""图片来源 —— 优先 Unsplash 搜索；失败时返回 None（App 端 fallback 到 SF Symbol）。

Unsplash 免费 demo key 50 req/h，每天 3 篇绝对够。
key 缺失时直接返回 None，pipeline 不当作错误（logging 警告）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)

UNSPLASH_API = "https://api.unsplash.com/search/photos"


def fetch_image(query: str, output: Path, fallback_url: str | None = None) -> bool:
    """根据查询词找一张图，下载到 output。成功返回 True，失败 False。

    fallback_url：如果 Wikinews 抓回来已经有图片 URL，直接下；不走 Unsplash。
    """
    output.parent.mkdir(parents=True, exist_ok=True)

    if fallback_url:
        try:
            return _download(fallback_url, output)
        except Exception as e:
            log.warning("fallback image failed (%s): %s", fallback_url, e)

    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        log.info("UNSPLASH_ACCESS_KEY not set; skip image fetch")
        return False

    try:
        r = requests.get(
            UNSPLASH_API,
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            log.info("Unsplash no results for: %s", query)
            return False
        image_url = results[0]["urls"]["regular"]
        return _download(image_url, output)
    except Exception as e:
        log.warning("Unsplash fetch failed for %r: %s", query, e)
        return False


def _download(url: str, output: Path) -> bool:
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    output.write_bytes(r.content)
    log.info("Saved image %s (%d bytes)", output.name, len(r.content))
    return True
