"""一次性脚本：扫 articles/ 给所有缺图的文件夹补一张 Unsplash 图，
然后重建 index.json 让 imagePath 填上。

环境变量：
    UNSPLASH_ACCESS_KEY  必需
    YOMU_REBACKFILL=1    可选——强制重抓所有图（覆盖已有的）

用法：
    GitHub Actions：触发 backfill-images workflow
    本地：UNSPLASH_ACCESS_KEY=xxx python scripts/backfill_images.py
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
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


def best_queries(folder: Path) -> list[str]:
    """优先用 vocab 的英文释义（最贴近文章内容），次用 title。"""
    queries: list[str] = []
    for tier in ["n3", "n5n4", "n2n1"]:
        f = folder / f"{tier}.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text("utf-8"))
        except Exception as e:
            log.warning("Cannot parse %s: %s", f, e)
            continue

        # 1) 抽前 3 个非动词 vocab 的英文释义
        kws: list[str] = []
        for v in data.get("vocabulary", []):
            m = (v.get("meaningEn") or "").strip()
            if not m or m.lower().startswith("to "):
                continue
            first = m.replace(";", ",").split(",")[0].strip()
            if first and first not in kws:
                kws.append(first)
            if len(kws) >= 3:
                break
        if kws:
            queries.append(" ".join(kws))

        # 2) 文章 title 作 fallback
        title = (data.get("title") or "").strip()
        if title:
            queries.append(title)
        break

    if not queries:
        queries.append(folder.name)
    return queries


def main() -> int:
    if not ARTICLES_ROOT.exists():
        log.error("articles/ not found")
        return 1

    force = os.environ.get("YOMU_REBACKFILL", "").lower() in {"1", "true", "yes"}
    log.info("force-rebackfill = %s", force)

    folders = sorted(p for p in ARTICLES_ROOT.iterdir() if p.is_dir())
    log.info("Scanning %d folders", len(folders))

    backfilled = skipped = failed = 0
    for folder in folders:
        image_path = folder / "image.jpg"
        if image_path.exists() and not force:
            skipped += 1
            continue

        queries = best_queries(folder)
        log.info("[%s] queries: %s", folder.name, queries)
        try:
            ok = images.fetch_image(
                output=image_path,
                queries=queries,
                slug=folder.name,
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
