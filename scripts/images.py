"""图片来源 —— 优先 Unsplash 搜索（带 fallback 列表），最终保底 'japan'。

策略：
  - fetch_image(queries=[...], slug=...) 按顺序试，第一个有结果就下；都空就返回 False
  - 每个查询拉前 30 张结果，用 slug hash 选一张 → 同一查询下不同文章拿不同图，
    且对同一 slug 是确定性的（不会每次跑出现抖动）
  - pipeline.py 传 [日文主题, 英文类别, 'japan']
  - backfill_images.py 传 [文章标题, 'japan']

Unsplash 免费 demo key 50 req/h，每天 3 篇 + backfill 都够。
key 缺失时直接返回 False，pipeline 不当作错误（logging 警告）。
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Iterable

import requests

log = logging.getLogger(__name__)

UNSPLASH_API = "https://api.unsplash.com/search/photos"

# 类别 → 英文搜索关键词，给 pipeline 用作 fallback
CATEGORY_TO_ENGLISH: dict[str, str] = {
    "anime":    "japanese anime",
    "food":     "japanese food",
    "travel":   "japan travel",
    "tech":     "technology japan",
    "culture":  "japanese culture",
    "society":  "tokyo street",
    "sports":   "sports stadium",
    "seasonal": "japan seasons",
    "news":     "tokyo skyline",
}


def fetch_image(
    output: Path,
    *,
    query: str | None = None,
    queries: Iterable[str] | None = None,
    slug: str | None = None,
    fallback_url: str | None = None,
) -> bool:
    """下一张图到 output。成功返回 True。

    queries：按顺序尝试的搜索词列表（推荐用法）；
    query：兼容旧调用（单个搜索词，等价于 queries=[query]）；
    slug：用于在 30 张候选里挑一张确定性结果，让同一查询下不同文章拿不同图；
          缺省时用 output 父目录名当 slug。
    fallback_url：直链下载（绕过 Unsplash），用于 Wikinews 自带原图等。
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

    if not slug:
        slug = output.parent.name

    qlist: list[str] = []
    if queries is not None:
        qlist.extend(queries)
    if query:
        qlist.append(query)
    if "japan" not in qlist:
        qlist.append("japan")

    for q in qlist:
        q = (q or "").strip()
        if not q:
            continue
        if _try_search(q, output, key, slug):
            return True

    return False


def _try_search(query: str, output: Path, key: str, slug: str) -> bool:
    """单次 Unsplash 搜索 + 下载，成功 True，无结果或错误 False。
    拉 30 张候选，用 slug hash 选一张 → 同 query 不同 slug 拿不同图，且对同一 slug 稳定。
    """
    try:
        r = requests.get(
            UNSPLASH_API,
            params={"query": query, "per_page": 30, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            log.info("Unsplash no results for: %s", query)
            return False
        # slug hash → idx，确定性 + 分散
        h = int(hashlib.md5(slug.encode("utf-8")).hexdigest(), 16)
        idx = h % len(results)
        image_url = results[idx]["urls"]["regular"]
        log.info("Unsplash hit for %r (idx %d/%d) → downloading", query, idx, len(results))
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
