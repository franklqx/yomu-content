"""内容源选择 —— 决定每天 3 篇怎么生成。

策略（valiant-foraging-gem.md 已批准）：
- 每天 2 篇 AI 原创（topic_seeds.json 里轮换）
- 每天 1 篇 Wikinews 改写（feed 失败时降级为全部 AI）
- 已用过的 seed 记录在 used_seeds.json，避免短期内重复
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from dateutil import parser as date_parser

from gemini import Seed

log = logging.getLogger(__name__)

WIKINEWS_FEED = "https://ja.wikinews.org/w/index.php?title=Special:NewPages&feed=rss&namespace=0"
USED_SEEDS_FILE = "used_seeds.json"


# ============================================================================
# AI 主题种子选择
# ============================================================================

class TopicSeeder:
    def __init__(self, seeds_file: Path, used_file: Path):
        self.seeds_file = seeds_file
        self.used_file = used_file
        self.seeds: dict[str, list[str]] = json.loads(seeds_file.read_text("utf-8"))
        self.used: list[str] = self._load_used()

    def _load_used(self) -> list[str]:
        if self.used_file.exists():
            try:
                return json.loads(self.used_file.read_text("utf-8"))
            except Exception:
                return []
        return []

    def _save_used(self) -> None:
        # 只保留最近 90 天的记录，避免 used_seeds 无限膨胀
        self.used = self.used[-200:]
        self.used_file.write_text(
            json.dumps(self.used, ensure_ascii=False, indent=2), "utf-8"
        )

    def pick(self, count: int, today: dt.date) -> list[Seed]:
        """从未用过的 seed 里挑 count 个，类别按日期 hash 轮换。"""
        categories = list(self.seeds.keys())

        # 按日期 hash 决定起始 category index，每天轮换
        date_hash = int(hashlib.md5(str(today).encode()).hexdigest(), 16)
        start = date_hash % len(categories)

        picked: list[Seed] = []
        used_set = set(self.used)
        for i in range(count):
            cat = categories[(start + i) % len(categories)]
            for seed in self.seeds[cat]:
                if seed not in used_set:
                    picked.append(Seed(
                        topic_ja=seed,
                        category=cat,
                        description_en=f"A Japanese learning article about {seed} ({cat}).",
                    ))
                    used_set.add(seed)
                    self.used.append(seed)
                    break
            else:
                # 该类别全用过了：从该类别随机取一个旧的（极小概率走到这里）
                seed = self.seeds[cat][date_hash % len(self.seeds[cat])]
                picked.append(Seed(topic_ja=seed, category=cat,
                                   description_en=f"Article about {seed} ({cat})."))

        self._save_used()
        return picked


# ============================================================================
# Wikinews 抓取
# ============================================================================

class WikinewsScraper:
    """从日文维基新闻 RSS 拿最新 1 篇做改写灵感（CC-BY 2.5，可商用）。"""

    def fetch_latest(self, max_age_days: int = 7) -> Seed | None:
        try:
            feed = feedparser.parse(WIKINEWS_FEED)
            if not feed.entries:
                log.warning("Wikinews feed empty")
                return None
            cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
            for entry in feed.entries[:20]:
                # entry.published 是 RFC 822；feedparser 有时给 published_parsed
                try:
                    pub = date_parser.parse(entry.published)
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=dt.timezone.utc)
                except Exception:
                    pub = dt.datetime.now(dt.timezone.utc)
                if pub < cutoff:
                    continue
                title = entry.title.strip()
                summary = self._strip_html(entry.get("summary", ""))[:300]
                return Seed(
                    topic_ja=title,
                    category="news",
                    description_en="Recent Wikinews JA article. Use as topic inspiration only.",
                    source_url=entry.link,
                    source_summary=summary,
                )
            log.warning("Wikinews: no recent entry within %d days", max_age_days)
            return None
        except Exception as e:
            log.warning("Wikinews fetch failed: %s", e)
            return None

    @staticmethod
    def _strip_html(html: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", "", html)
        return re.sub(r"\s+", " ", text).strip()


# ============================================================================
# 组合策略
# ============================================================================

def pick_sources(
    today: dt.date,
    seeds_file: Path,
    used_file: Path,
    count: int = 3,
    wikinews_count: int = 1,
) -> list[Seed]:
    """每天的内容源 —— 默认 2 AI + 1 Wikinews，Wikinews 拉不到时改成 3 AI。"""
    sources: list[Seed] = []

    if wikinews_count > 0:
        wn = WikinewsScraper().fetch_latest()
        if wn:
            sources.append(wn)
            log.info("Using Wikinews seed: %s", wn.topic_ja)
        else:
            log.warning("Wikinews unavailable; using all-AI seeds today")
            wikinews_count = 0

    seeder = TopicSeeder(seeds_file=seeds_file, used_file=used_file)
    sources.extend(seeder.pick(count - wikinews_count, today))
    return sources
