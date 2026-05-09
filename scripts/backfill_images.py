"""一次性脚本：扫 articles/ 给所有缺图的文件夹补一张 Unsplash 图，
然后重建 index.json 让 imagePath 填上。

用法：
    GitHub Actions：触发 backfill-images workflow
    本地：UNSPLASH_ACCESS_KEY=xxx python scripts/backfill_images.py
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from pathlib import Path

import builder
import images

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("backfill")

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_ROOT = REPO_ROOT / "articles"


def best_query(folder: Path) -> str:
    """从文件夹里第一个能读的 tier JSON 取 title 当搜索词。"""
    for tier in ["n3", "n5n4", "n2n1"]:
        f = folder / f"{tier}.json"
        if f.exists():
            try:
                data = json.loads(f.read_text("utf-8"))
                title = (data.get("title") or "").strip()
                if title:
                    return title
            except Exception as e:
                log.warning("Cannot parse %s: %s", f, e)
    return folder.name


def main() -> int:
    if not ARTICLES_ROOT.exists():
        log.error("articles/ not found")
        return 1

    folders = sorted(p for p in ARTICLES_ROOT.iterdir() if p.is_dir())
    log.info("Scanning %d folders", len(folders))

    backfilled = skipped = failed = 0
    for folder in folders:
        image_path = folder / "image.jpg"
        if image_path.exists():
            skipped += 1
            continue

        query = best_query(folder)
        log.info("[%s] querying: %s", folder.name, query)
        try:
            # backfill 没法拿到 category，三层 fallback：标题 → "japanese news" → "japan"
            ok = images.fetch_image(
                output=image_path,
                queries=[query, "japanese news", "japan"],
            )
            if ok:
                backfilled += 1
            else:
                failed += 1
        except Exception as e:
            log.warning("[%s] failed: %s", folder.name, e)
            failed += 1

    log.info("Done — backfilled=%d, skipped=%d, failed=%d", backfilled, skipped, failed)

    # 重建 index.json 让 imagePath 字段填上
    today = dt.date.today()
    builder.rebuild_index(ARTICLES_ROOT, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
