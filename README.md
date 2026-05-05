# yomu-content

Public content repository for [Yomu](https://github.com/franklqx/Yomu) —— iOS Japanese learning app.

## What's here

- `articles/` —— 每日 pipeline 产出的文章 JSON + 音频 MP3 + 图片
  - `articles/index.json` —— 最近 30 天的索引，App 启动时拉这个
  - `articles/YYYY-MM-DD-slug/` —— 单篇文章三档全资源
- `scripts/` —— 内容生成 pipeline（Python）
- `.github/workflows/` —— 每日 GitHub Actions 自动跑

## Pipeline

每天 06:00 JST（21:00 UTC 前一天）由 GitHub Actions 触发：

```
seed 选择   →  Gemini 三档生成  →  edge-tts MP3
   │              │                    │
 (2 AI +     (title/段落/翻译/      (每档 1 个
  1 Wikinews)  vocab/quiz)           MP3 文件)
                  │
              Unsplash 配图（可选）
                  │
              builder.py 写文件 + 重建 index.json
                  │
              git commit + push  →  GitHub Pages 自动部署
```

## Manual trigger

```
# GitHub UI: Actions → Daily content → Run workflow
# 可选填日期补跑历史：YYYY-MM-DD
```

或本地：

```bash
export GEMINI_API_KEY="..."
export UNSPLASH_ACCESS_KEY="..."  # 可选
pip install -r scripts/requirements.txt
python scripts/pipeline.py
```

## Schema

`articles/{slug}/{tier}.json` 严格对齐 iOS `Article.swift` 的 Codable 结构。详见 Yomu repo 的 `docs/SCHEMA.md`。

`articles/index.json`：

```json
{
  "version": "1.0",
  "generatedAt": "2026-05-04T21:00:00+00:00",
  "articles": [
    {
      "slug": "2026-05-04-akihabara-robot-cafe",
      "publishedAt": "2026-05-04T06:00:00+09:00",
      "imagePath": "articles/2026-05-04-akihabara-robot-cafe/image.jpg",
      "audioPaths": {
        "n5n4": "articles/2026-05-04-akihabara-robot-cafe/audio_n5n4.mp3",
        "n3":   "articles/2026-05-04-akihabara-robot-cafe/audio_n3.mp3",
        "n2n1": "articles/2026-05-04-akihabara-robot-cafe/audio_n2n1.mp3"
      },
      "tiers": ["n5n4", "n3", "n2n1"]
    }
  ]
}
```

## License

- Pipeline scripts: MIT
- Generated articles: CC-BY-SA 4.0（详见 LICENSE）
- Wikinews 改写文章保留来源链接（CC-BY 2.5 上游许可）

## Hosted at

GitHub Pages: https://franklqx.github.io/yomu-content/
