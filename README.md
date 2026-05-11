# memex — 外置大脑

> "The owner of the memex... can add marginal notes and comments... His trails do not fade. Several years later, his talk with a friend turns to the queer ways in which a people resist innovations, even of vital interest. He has an example..."
> —— Vannevar Bush, *As We May Think*, 1945

**memex** = 个人知识 specialist agent service。任何 MCP-supporting client（Claude Code / Claude Desktop / Cursor / openclaw / 等）都能让它帮自己消化内容 + 回答专业问题。

## 定位

跟 Wikipedia / Notion / Obsidian / Logseq 的区别：
- 它们是 **knowledge tool**（你来用，知识在那里）
- memex 是 **knowledge agent service**（agent 来用，memex 主动维护 + 综合输出）

跟普通 RAG 的区别：
- RAG 切 chunk 模糊检索
- memex 按 concept 组织 + LLM 维护一致性 + Karpathy-style 三铁律守门

## 不变量（design invariants）

1. **单租户分散部署** —— 每人跑自己一份，知识是私人 asset
2. **LLM as glue, not orchestrator** —— LLM 是被代码调用的 function，代码是 driver
3. **Specialist agent service, not general** —— 只做知识管理 / 录入 / 综合 / 查询；不做 dialogue / web search / 任务编排
4. **Provider 中立** —— OpenAI-compat endpoint 即可（mimo / DeepSeek / OpenAI / Anthropic / 任何）

## 当前状态：Phase 0 spike

正在验证 mimo 能否担纲 wiki digest 任务。

`spike_digest.py` 是 Milestone 0 验证脚本：
- 输入：一个 source（默认 llm-wiki 项目里的 `docs/qingang_LiEA12.md`）
- 跑：grep wiki 找候选相关页 → 一次 mimo call → 解析 JSON → 输出 stdout
- 输出：mimo 想做的 wiki 改动（JSON 格式）
- **不写 wiki / 不 git commit** —— 纯 read-only，人工对比 Opus 4.7 已 commit 的 baseline

## How to run

```bash
/home/leon/llm-wiki/.venv-mcp/bin/python3 /home/leon/memex/spike_digest.py
```

（暂时复用 llm-wiki 仓库的 `.venv-mcp` 环境——它装了 `openai`，够用）

## Decision matrix（看完 spike 输出做什么）

| 质量 | 决策 |
|------|------|
| ≥ 80% Opus baseline | Phase 1 全力推进 standalone service |
| 60-80% | hybrid（mimo first-pass + Opus refine） |
| < 60% | 暂停 standalone，换 LLM provider 或等 mimo 升级 |

人工 spot-check 项：
- 核心数字精度（L = 26.5 AU / k = 13 / 8192 cells / 谱 -1.65~-1.72）
- 三铁律守度（concept first / sources feed / no source-specific pages）
- Frontmatter 字段完整 + sources 字段准确
- Wikilink 目标可达（不悬链）
- 没 hallucination

## Roadmap

```
Phase 0 (现在)   spike — 验证 mimo digest 能力
Phase 1          MVP service — 串行 digest + 简单 query + MCP entry
Phase 2          多 source 并行 + worktree isolation + reviewer pass
Phase 3          file watcher + pending queue + enrich worker
Phase 4          docker / 文档 / 5 分钟 quickstart / 开箱即用
Phase 5          开源发布
```

## Stack（确定 + 不变）

- Python 3.11+
- openai SDK（OpenAI-compat client）
- FastMCP（MCP server，未来 Phase 1 引入）
- 标准库 multiprocessing / asyncio / subprocess
- 暂不引：LangGraph / CrewAI / LangChain / Celery / Redis（都是 over-engineering）

## What's NOT in memex（边界）

- ❌ Web research / 搜索引擎（user agent 自己干）
- ❌ Dialogue / chat UI（client 干）
- ❌ 任务编排 / orchestration（client 干）
- ❌ 多 user / 团队协作（永远单租户）
- ❌ Vector DB / embedding search（grep + 概念组织已足够 personal scale）

## 历史 / 致敬

- **Vannevar Bush** *As We May Think* (1945) —— "memex" 概念源头
- **Karpathy LLM Wiki** [gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) —— concepts first / sources feed concepts / no source-specific pages 三铁律
- **`/home/leon/llm-wiki/`** —— 我们的 Phase 0 起点，存放实际 wiki 数据 + 历史 Claude Code skill 经验

## 跟 llm-wiki 的关系

```
/home/leon/llm-wiki/    ← 现有 wiki repo（数据 + Claude Code skill / sub-agent 工作流）
/home/leon/memex/       ← 本 repo（standalone service，会读 llm-wiki 的 docs/ wiki/）
```

Phase 0 - 4 期间，memex service 读 llm-wiki 仓库的 docs/ + wiki/ 作为数据。Phase 5 开源后，用户给 memex service 配自己的 wiki 路径即可。
