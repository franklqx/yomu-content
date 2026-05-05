"""Gemini API wrapper.

每篇文章每档调一次 generate_article()，返回完整的 Article JSON dict
（与 iOS Article.swift Codable schema 对齐）。

依赖 google-genai SDK + GEMINI_API_KEY 环境变量。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

# 每档的指标 —— 严格控制句长 / 词汇 / quiz 数，跟 PLAN.md 对齐
TIER_SPEC = {
    "n5n4": {
        "level_label": "N5–N4 初学者",
        "guidance": (
            "用最基础的语法（です/ます调、过去时、て形）。"
            "句子短（每句 15-25 字以内），尽量只用 N5/N4 词汇。"
            "避免敬语、复杂从句、专业术语。"
        ),
        "quiz_count": 1,
    },
    "n3": {
        "level_label": "N3 中级",
        "guidance": (
            "用日常表达 + 复合句（から/ので/のに、ば/たら、ても、ながら）。"
            "句长适中（25-50 字）。可以含少量专业词，但要在 vocabulary 里解释。"
            "避免书面语、古典语法。"
        ),
        "quiz_count": 2,
    },
    "n2n1": {
        "level_label": "N2–N1 进阶",
        "guidance": (
            "用书面语 / 新闻体（〜とのこと、〜と見られる、〜に伴い 等）。"
            "可用敬语、被动使役、抽象名词、长复句（50-80 字）。"
            "目标读起来像真实日本新闻。"
        ),
        "quiz_count": 3,
    },
}


@dataclass
class Seed:
    """生成文章的种子信息。"""

    topic_ja: str           # 日文主题（"秋葉原の新ロボットカフェ" 等）
    category: str           # 类别（anime/food/travel/...）
    description_en: str = ""  # 给 Gemini 的英文背景说明（提高准确性）
    source_url: str | None = None  # Wikinews 来源（A 路线）才有
    source_summary: str | None = None  # Wikinews 原始摘要（仅作灵感）


class GeminiClient:
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY 未设置")
        self.client = genai.Client(api_key=api_key)

    def generate_article(self, seed: Seed, tier: str) -> dict[str, Any]:
        """对单档生成完整 Article（含 paragraphs / vocab / quiz / 翻译）。

        重试 2 次 + 失败时降级（去掉 quiz / vocab，保最低段落输出）。
        返回的 dict 直接对应 iOS Article.swift 的 JSON schema。
        """
        if tier not in TIER_SPEC:
            raise ValueError(f"unknown tier {tier}")

        spec = TIER_SPEC[tier]
        prompt = self._build_prompt(seed, tier, spec)

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.85,
                        max_output_tokens=4096,
                        system_instruction=(
                            "你是日语学习内容编辑。生成的文章必须：\n"
                            "1. 内容自然、准确、适合学习\n"
                            "2. 严格输出 JSON，不要 markdown 围栏\n"
                            "3. 避开政治、暴力、成人话题\n"
                            "4. 引用任何商业新闻只取话题灵感，绝不复制原文\n"
                        ),
                    ),
                )
                payload = self._parse(resp.text)
                self._validate(payload, spec, tier)
                return self._normalize(payload, seed, tier)
            except Exception as e:
                last_err = e
                log.warning(
                    "Gemini attempt %d/3 failed for %s/%s: %s",
                    attempt + 1, seed.topic_ja, tier, e,
                )
                time.sleep(2 ** attempt)

        raise RuntimeError(
            f"Gemini failed 3x for tier={tier}, topic={seed.topic_ja}: {last_err}"
        )

    # ------------------------------------------------------------------

    def _build_prompt(self, seed: Seed, tier: str, spec: dict) -> str:
        source_hint = ""
        if seed.source_url:
            source_hint = (
                f"\n参考来源（仅取话题，禁止复制原文）：{seed.source_url}\n"
                f"来源摘要：{seed.source_summary or ''}\n"
            )

        return f"""请为日语学习者生成一篇 **{spec['level_label']}** 难度的日语文章，主题：{seed.topic_ja}

类别：{seed.category}
英文背景：{seed.description_en}
{source_hint}

难度要求：{spec['guidance']}

输出严格 JSON，结构如下（不要任何 markdown 围栏、不要解释）：

{{
  "title": "<日文标题，吸引读者，{ '15 字以内' if tier == 'n5n4' else '25 字以内' }>",
  "summary": "<日文摘要，1-2 句话>",
  "estimatedMinutes": <预计阅读分钟，1-5 之间整数>,
  "paragraphs": [
    {{
      "text": "<日文原文段落>",
      "translationZh": "<完整中文翻译，自然流畅>",
      "translationEn": "<完整英文翻译，自然流畅>"
    }},
    ... (共 3-4 段)
  ],
  "vocabulary": [
    {{
      "word": "<日文词>",
      "reading": "<假名读音>",
      "meaningZh": "<中文释义>",
      "meaningEn": "<英文释义>",
      "level": "<n5n4 | n3 | n2n1>",
      "exampleSentence": "<日文例句，可省略写 null>"
    }},
    ... (共 5-8 个能帮助理解本档文章的词)
  ],
  "quiz": [
    {{
      "question": "<日文阅读理解问题>",
      "options": ["<选项1>", "<选项2>", "<选项3>", "<选项4>"],
      "correctIndex": <0-3 整数>,
      "explanation": "<日文解析，引用文中原句>"
    }},
    ... (共 {spec['quiz_count']} 道)
  ]
}}

注意：
- paragraphs 数量必须 3-4 段
- vocabulary 数量 5-8 个，level 字段只能是 n5n4/n3/n2n1 三个值
- quiz 数量必须正好 {spec['quiz_count']} 道
- correctIndex 是数字 0/1/2/3
- 全文不得复制任何商业新闻原文，只能取话题
"""

    def _parse(self, text: str) -> dict:
        text = text.strip()
        # Gemini 偶尔会包 ```json ... ``` 围栏，兜底剥一下
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return json.loads(text)

    def _validate(self, p: dict, spec: dict, tier: str) -> None:
        for k in ["title", "summary", "estimatedMinutes", "paragraphs", "vocabulary", "quiz"]:
            if k not in p:
                raise ValueError(f"missing key: {k}")
        if not isinstance(p["paragraphs"], list) or not (3 <= len(p["paragraphs"]) <= 4):
            raise ValueError(f"paragraphs must be 3-4 items, got {len(p.get('paragraphs', []))}")
        if not isinstance(p["vocabulary"], list) or not (3 <= len(p["vocabulary"]) <= 10):
            raise ValueError(f"vocabulary count off: {len(p.get('vocabulary', []))}")
        if len(p["quiz"]) != spec["quiz_count"]:
            raise ValueError(
                f"quiz count must be {spec['quiz_count']} for tier {tier}, got {len(p['quiz'])}"
            )
        valid_levels = {"n5n4", "n3", "n2n1"}
        for v in p["vocabulary"]:
            if v.get("level") not in valid_levels:
                v["level"] = tier  # 兜底归到当前档
        for q in p["quiz"]:
            if not isinstance(q.get("correctIndex"), int) or not 0 <= q["correctIndex"] <= 3:
                raise ValueError(f"bad correctIndex: {q.get('correctIndex')}")
            if not isinstance(q.get("options"), list) or len(q["options"]) != 4:
                raise ValueError("quiz options must be 4")

    def _normalize(self, p: dict, seed: Seed, tier: str) -> dict:
        """注入 UUID + slug + tier + sourceURL，匹配 iOS Article schema。"""
        for para in p["paragraphs"]:
            para.setdefault("id", str(uuid.uuid4()))
            para.setdefault("audioStartMs", None)
            para.setdefault("audioEndMs", None)
            para.setdefault("translationZh", None)
            para.setdefault("translationEn", None)
        for v in p["vocabulary"]:
            v.setdefault("id", str(uuid.uuid4()))
            v.setdefault("exampleSentence", None)
        for q in p["quiz"]:
            q.setdefault("id", str(uuid.uuid4()))

        p["tier"] = tier
        p["sourceURL"] = seed.source_url  # null 也写出，iOS Optional 支持
        return p
