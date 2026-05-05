"""每日内容 pipeline 主入口。

流程：
    1. 选今天的 3 个 seed（2 AI + 1 Wikinews）
    2. 每个 seed 生成 3 档 article JSON
    3. 每档生成 MP3
    4. 每篇配一张图（Unsplash / Wikinews）
    5. 重建 index.json
    6. 失败的篇跳过，不阻塞其他

环境变量：
    GEMINI_API_KEY        必需
    UNSPLASH_ACCESS_KEY   可选（无则跳过配图）
    YOMU_DATE             可选，覆盖"今天"（YYYY-MM-DD），用于补跑
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path

from dateutil import tz

import builder
import images
import sources
import tts
from gemini import GeminiClient, Seed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pipeline")

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_ROOT = REPO_ROOT / "articles"
SEEDS_FILE = Path(__file__).resolve().parent / "topic_seeds.json"
USED_FILE = Path(__file__).resolve().parent / "used_seeds.json"

JST = tz.gettz("Asia/Tokyo")
TIERS = ["n5n4", "n3", "n2n1"]


def today_jst() -> dt.date:
    """优先用 YOMU_DATE 环境变量，否则取 JST 当前日期。"""
    override = os.environ.get("YOMU_DATE", "").strip()
    if override:
        return dt.date.fromisoformat(override)
    return dt.datetime.now(JST).date()


def process_seed(seed: Seed, today: dt.date, gemini: GeminiClient) -> bool:
    """处理单个 seed —— 生成 3 档 + 音频 + 图片。返回是否全部成功。"""
    slug = builder.make_slug(today, seed.topic_ja)
    folder = ARTICLES_ROOT / slug
    published_at = dt.datetime(today.year, today.month, today.day, 6, 0, tzinfo=JST)

    log.info("=" * 60)
    log.info("Processing seed: %s [%s] -> %s", seed.topic_ja, seed.category, slug)

    success_tiers: list[str] = []
    paragraphs_by_tier: dict[str, list[str]] = {}

    for tier in TIERS:
        try:
            article = gemini.generate_article(seed, tier)
            builder.write_article(article, slug, tier, published_at, ARTICLES_ROOT)
            paragraphs_by_tier[tier] = [p["text"] for p in article["paragraphs"]]
            success_tiers.append(tier)
        except Exception as e:
            log.error("Tier %s failed for %s: %s", tier, slug, e)

    if not success_tiers:
        log.error("No tier succeeded for %s; abandoning", slug)
        # 清掉空文件夹（如果只有元信息没产物）
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        return False

    # TTS（每档独立失败容忍 —— 文章 JSON 已经写了，App 端可以读字不能听）
    for tier in success_tiers:
        try:
            tts.synthesize_article(
                paragraphs=paragraphs_by_tier[tier],
                tier=tier,
                output=folder / f"audio_{tier}.mp3",
            )
        except Exception as e:
            log.error("TTS failed for %s/%s: %s", slug, tier, e)

    # 图片（可选）
    try:
        # Wikinews 来源时不传 fallback_url（v1 不抓 wiki 原图，避免许可证麻烦）
        images.fetch_image(
            query=seed.topic_ja + " " + seed.category,
            output=folder / "image.jpg",
        )
    except Exception as e:
        log.warning("Image fetch failed for %s: %s", slug, e)

    return True


def main() -> int:
    today = today_jst()
    log.info("Yomu daily content pipeline | date=%s JST", today)

    if not os.environ.get("GEMINI_API_KEY"):
        log.error("GEMINI_API_KEY missing")
        return 2

    ARTICLES_ROOT.mkdir(parents=True, exist_ok=True)

    seeds = sources.pick_sources(
        today=today,
        seeds_file=SEEDS_FILE,
        used_file=USED_FILE,
        count=3,
        wikinews_count=1,
    )
    log.info("Selected %d seeds:", len(seeds))
    for s in seeds:
        log.info("  - [%s] %s%s", s.category, s.topic_ja,
                 f" (source: {s.source_url})" if s.source_url else "")

    gemini = GeminiClient()

    success_count = 0
    for seed in seeds:
        try:
            if process_seed(seed, today, gemini):
                success_count += 1
        except Exception as e:
            log.exception("Seed %r crashed: %s", seed.topic_ja, e)

    log.info("Generated %d/%d articles", success_count, len(seeds))

    builder.rebuild_index(ARTICLES_ROOT, today)

    if success_count == 0:
        log.error("All seeds failed; pipeline considered failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
