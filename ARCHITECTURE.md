# memex Architecture

> 给开源 reader / contributor 看 high-level。Code-level 见 service/ 各 module docstring。

## 三句话理解 memex

1. **memex 是个 specialist agent service** —— 你的 wiki 是它的 long-term memory，它扮演该 wiki 涵盖领域的"专家"角色。
2. **对外通过 MCP** —— 任何 MCP client (Claude Code / Cursor / Codex / Desktop / ...) 调用 12 个 tool。
3. **不是 agent system** —— LLM 是被代码调用的 function，代码是 driver。无 agent framework。

## 系统形态

```
┌──────────────────────────────────────────────────────────────┐
│                       Client Agents                          │
│  Claude Code / Cursor / Claude Desktop / Codex / ...         │
└──────────────────────────────────────────────────────────────┘
              │ MCP (stdio | HTTP)
              ↓
┌──────────────────────────────────────────────────────────────┐
│                    memex MCP server                          │
│                  (FastMCP, 12 tools)                         │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐   │
│  │   ingest    │   expert    │    read     │   admin     │   │
│  │             │             │             │             │   │
│  │ • ingest_   │ • ask_      │ • search    │ • status    │   │
│  │   source    │   expert    │ • read      │ • pending   │   │
│  │ • apply_    │             │ • index     │ • pending_  │   │
│  │   staging   │             │ • recent_   │   applies   │   │
│  │             │             │   changes   │ • guide     │   │
│  │             │             │ • stats     │             │   │
│  └─────────────┴─────────────┴─────────────┴─────────────┘   │
└──────────────────────────────────────────────────────────────┘
              ↓                              ↑
┌──────────────────────────────┐    ┌──────────────────────┐
│   LLM provider (mimo /       │    │   Wiki repo (git)    │
│   OpenAI / DeepSeek / 任意   │    │   wiki/ docs/ raw/   │
│   OpenAI-compat endpoint)    │    │   memex 自动 commit  │
└──────────────────────────────┘    └──────────────────────┘
              ↑                              ↑
┌──────────────────────────────────────────────────────────────┐
│  File watcher (optional systemd service)                     │
│  raw/X 落地 → preprocess.py → docs/Y → digest pipeline       │
└──────────────────────────────────────────────────────────────┘
```

## 数据流

### Ingest 路径 (写入 wiki)

```
1. raw/X.pdf 落地 (用户 / 别的 agent 投递)
        ↓
2. preprocess (复用 llm-wiki/tools/preprocess.py)
   PDF/音频/视频/电子书/图片 → docs/X.md (markdown)
        ↓
3. digest pipeline:
   a. retriever: grep wiki/ 找 15 个候选相关页
   b. build prompt: source + candidates + INDEX
   c. mimo LLM call (1st): 输出 digest JSON
   d. validator: schema check + 三铁律 lint
   e. (if --review) mimo LLM call (2nd): reviewer audit
   f. (if review issues) mimo LLM call (3rd): fix call
   g. apply edits → .staging/ (镜像 wiki/，不动 production)
        ↓
4. caller / owner 调 wiki_apply_staging:
   a. 复制 .staging/ → wiki/ (production)
   b. git add + commit (per-source 一个 commit)
   c. 不 push (owner 手动)
```

### Query 路径 (读 wiki)

```
caller agent: "什么是 SEP-Reservoir 效应？"
        ↓
1. wiki_ask_expert(question) MCP call
        ↓
2. memex 内部:
   a. retriever: grep wiki/ 找 top-5 (quick) / top-12 (deep)
   b. 读 5-12 个完整页内容
   c. build prompt: source + question + wiki context
   d. mimo LLM call: synthesize answer (像专家综合)
   e. parse JSON: {answer, citations, confidence, ...}
        ↓
3. 返回结果给 caller
        ↓
4. caller 直接呈现给 end user (不必再读 wiki markdown)
```

## Module 职责

| Module | 责任 | Lines |
|------|------|---|
| `config.py` | yaml + env 4 级 fallback loader | ~150 |
| `prompts.py` | 3 个 system prompt (digest / reviewer / expert) | ~200 |
| `llm.py` | OpenAI-compat client wrapper, JSON mode + fallback | ~50 |
| `retriever.py` | grep 候选 wiki 页 + 构造 LLM context | ~100 |
| `validator.py` | JSON parse (lenient) + schema check + 三铁律 lint | ~150 |
| `staging.py` | 应用 LLM edits → .staging/ + frontmatter merge | ~150 |
| `digest.py` | digest pipeline 入口 (含 retry + reviewer pass) | ~200 |
| `reviewer.py` | 2nd LLM call audit + is_pass / has_meaningful_issues | ~100 |
| `query.py` | RAG-style expert synthesis | ~100 |
| `git_ops.py` | promote staging → production + git commit | ~150 |
| `watcher.py` | watchdog 监控 raw/ + 触发 pipeline (可选 systemd) | ~250 |
| `mcp_server.py` | FastMCP server + 12 tools (ingest / expert / read / admin) | ~500 |
| **总计** | | **~2200** |

测试: 67 个 unit test 覆盖前 11 个 module (mcp_server 部分覆盖)。

## 关键设计决策

### 为什么没 agent framework

LangGraph / CrewAI / OpenAI Agents SDK 都为 agent system 设计。memex 是 service with LLM calls：
- LLM 不决定流程，代码决定
- 单 source digest 是直线 pipeline (4-7 step)，不是 emergent graph
- 引 framework = 学习曲线 + lock-in + abstraction tax
- 直接用 openai SDK 控制更多，代码量更少

### 为什么内嵌 LLM synthesis（wiki_ask_expert）

Karpathy LLM wiki gist 暗示 caller 应该自己读 INDEX + drill pages，不需要 server synth。但 memex 选择 server-side synth 因为：
- caller context 不被 wiki 内容污染
- memex 内部 LLM 用 owner's prompt（domain-tuned），caller 拿到的是"专家答复"语境
- 跟普通 RAG 的区别：page-level granularity (不切 chunks)，wiki 已经是 LLM-curated synthesis，server 再做一次 final synth 而非 raw retrieval

### 为什么 staging dir + 不 auto-commit

mimo (or 任何 LLM) 偶尔输出 bug / hallucination / 违反三铁律。auto-commit 到 production → 后悔难。
- staging 让 caller / owner review proposed edits
- wiki_apply_staging 默认 dry-run，apply=True 才真写
- commit per source（细粒度，易 git revert）

### 为什么永远不 git push

push 是 social action（推到 remote 公开）。memex 是单租户工具，不该替 owner 决定何时公开。owner 手动 push。

## Phase Roadmap

```
✅ P0  spike — 验证 mimo digest 能力
✅ P1  digest pipeline + reviewer + retry + git commit
✅ P2  MCP server + 12 tools + file watcher + expert agent
✅ P4  config 抽象 + Docker + CI + LICENSE + tests (67)
⏳ P3  并发 digest (multiprocessing) — performance, 非必需 MVP
⏳ P5  开源 — push to GitHub + community
```

## 测试策略

- **Pure logic** (validator / staging / config / git_ops): unit tests with tmp_path
- **Filesystem** (retriever): tmp wiki + 真 ripgrep
- **LLM-dependent** (digest / query / reviewer): mock OpenAI client
- **Stats / git** (mcp_server stats tools): tmp git repo + commits

测试**不**消耗 LLM API quota（全 mock），CI 友好。

## Out of scope

memex 故意**不做**这些（设计边界）：
- Web research / 搜索引擎 (caller agent 自己干)
- Dialogue / chat UI (client 干)
- 任务编排 / orchestration (client 干)
- 多 user / 团队协作 (永远单租户)
- Vector DB / embedding search (grep + concept 组织已够 personal scale)
- Auto git push (owner 手动)
- Agent reasoning (无 multi-step decision loop in server)

## 进一步阅读

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — 三铁律 + 通过 wiki 替代传统 RAG 的初始 vision
- [Vannevar Bush *As We May Think* (1945)](https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/) — "memex" 概念源头
- [MCP spec](https://modelcontextprotocol.io/) — Anthropic 主导的开放协议
