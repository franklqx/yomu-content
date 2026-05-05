"""edge-tts wrapper —— 把 Article 文本合成日语 MP3。

每档一份 audio_<tier>.mp3，整篇文章顺序拼接（段落间略停顿）。
段落级时间戳同步是 v2 的事；这一轮只做整篇朗读。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Iterable

import edge_tts

log = logging.getLogger(__name__)

# 选用 ja-JP-NanamiNeural（女声）作为默认；可在配置里切到 KeitaNeural（男声）
DEFAULT_VOICE = "ja-JP-NanamiNeural"

# 不同档调一下语速：初学者慢一点，进阶正常
RATE_BY_TIER = {
    "n5n4": "-15%",
    "n3":   "-5%",
    "n2n1": "+0%",
}


async def _synthesize_async(text: str, voice: str, rate: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(output))


def synthesize_article(
    paragraphs: Iterable[str],
    tier: str,
    output: Path,
    voice: str = DEFAULT_VOICE,
) -> None:
    """把段落列表合成单个 MP3。段落之间用句号 + 换行制造自然停顿。"""
    full_text = "\n\n".join(p.strip() for p in paragraphs if p.strip())
    if not full_text:
        raise ValueError("empty paragraphs")
    rate = RATE_BY_TIER.get(tier, "+0%")
    log.info("TTS %s tier=%s voice=%s rate=%s (%d chars)",
             output.name, tier, voice, rate, len(full_text))
    asyncio.run(_synthesize_async(full_text, voice, rate, output))
