"""把 Gemini 输出 + 音频 + 图片 拼成最终目录结构 + 重建 index.json。

输出结构：
    articles/
      YYYY-MM-DD-slug/
        n5n4.json
        n3.json
        n2n1.json
        audio_n5n4.mp3
        audio_n3.mp3
        audio_n2n1.mp3
        image.jpg            # 可选
      index.json             # 最近 30 天倒序
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

INDEX_VERSION = "1.0"
INDEX_RECENT_DAYS = 30
TIERS = ["n5n4", "n3", "n2n1"]


def make_slug(date: dt.date, topic_ja: str) -> str:
    """生成 URL 安全的 slug。日期 + 罗马字 hash 兜底（日文不直接进 URL）。"""
    safe = unicodedata.normalize("NFKC", topic_ja)
    safe = re.sub(r"[^A-Za-z0-9]+", "-", safe)
    safe = safe.strip("-").lower()
    if not safe:
        # 日文无 ASCII 字符时，用 hash 兜底
        import hashlib
        safe = hashlib.md5(topic_ja.encode("utf-8")).hexdigest()[:10]
    safe = safe[:40]
    return f"{date.isoformat()}-{safe}"


def write_article(
    article_dict: dict[str, Any],
    slug: str,
    tier: str,
    published_at: dt.datetime,
    articles_root: Path,
) -> Path:
    """写单档 article JSON。"""
    article_dict["slug"] = slug
    article_dict["publishedAt"] = published_at.isoformat()
    folder = articles_root / slug
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{tier}.json"
    out.write_text(
        json.dumps(article_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Wrote %s", out.relative_to(articles_root.parent))
    return out


def rebuild_index(articles_root: Path, today: dt.date) -> None:
    """扫 articles/ 目录，重建 index.json（倒序最近 N 天）。"""
    cutoff = today - dt.timedelta(days=INDEX_RECENT_DAYS)
    entries: list[dict[str, Any]] = []

    for folder in sorted(articles_root.iterdir(), reverse=True):
        if not folder.is_dir() or folder.name.startswith("."):
            continue

        # 文件夹名形如 YYYY-MM-DD-slug
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-", folder.name)
        if not m:
            continue
        try:
            folder_date = dt.date.fromisoformat(m.group(1))
        except Exception:
            continue
        if folder_date < cutoff:
            continue

        # 收集该 slug 实际有哪些档
        tiers_present = [t for t in TIERS if (folder / f"{t}.json").exists()]
        if not tiers_present:
            continue

        # 取一份 article JSON 拿 publishedAt（n3 优先，没就拿第一个有的）
        ref_tier = "n3" if "n3" in tiers_present else tiers_present[0]
        ref = json.loads((folder / f"{ref_tier}.json").read_text("utf-8"))
        published_at = ref.get("publishedAt") or folder_date.isoformat()

        # 图片 / 音频路径相对仓库根
        rel = f"articles/{folder.name}"
        image_path = f"{rel}/image.jpg" if (folder / "image.jpg").exists() else None
        audio_paths = {
            t: f"{rel}/audio_{t}.mp3"
            for t in tiers_present
            if (folder / f"audio_{t}.mp3").exists()
        }

        entries.append({
            "slug": folder.name,
            "publishedAt": published_at,
            "imagePath": image_path,
            "audioPaths": audio_paths,
            "tiers": tiers_present,
        })

    entries.sort(key=lambda e: e["publishedAt"], reverse=True)

    payload = {
        "version": INDEX_VERSION,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "articles": entries,
    }
    out = articles_root / "index.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Rebuilt %s with %d entries", out.relative_to(articles_root.parent), len(entries))
