# memex — 外置大脑

> "The owner of the memex... can add marginal notes and comments... His trails do not fade."
> —— Vannevar Bush, *As We May Think*, 1945

**memex** = 个人知识 specialist agent service。任何 MCP-supporting client（Claude Code / Claude Desktop / Cursor / 等）都能把它当**专家**问问题、让它消化新内容。

## 5 分钟 quickstart

**前置**：你有一个 wiki repo（git 仓库，包含 `wiki/` `docs/` `raw/` 等目录）。
没有就先建一个空的：
```bash
mkdir -p ~/my-wiki/{wiki/concepts,wiki/entities,docs,raw}
cd ~/my-wiki && git init -b main && git commit --allow-empty -m "init"
```

### A. Docker（最推荐）

```bash
docker run -d --name memex \
  -p 127.0.0.1:18766:18766 \
  -v $HOME/my-wiki:/data/wiki \
  -e MEMEX_API_KEY="sk-..." \
  -e MEMEX_BASE_URL="https://api.openai.com/v1" \
  -e MEMEX_DEFAULT_MODEL="gpt-4o-mini" \
  memex:latest
```

任何 OpenAI-compat endpoint 都能用（OpenAI / mimo / DeepSeek / Qwen / 自部署 vLLM / ...）。

### B. Python venv（dev / contributor）

```bash
git clone https://github.com/LeonJoeeee/memex.git
cd memex
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp memex.yaml.example memex.yaml   # 改成你自己的 wiki path + base_url
export XIAOMI_API_KEY="sk-..."     # 或者改 yaml 里的 api_key_env
python -m service.mcp_server --http
```

### 挂到 Claude Code

```bash
claude mcp add --transport http memex http://127.0.0.1:18766/mcp
```

Session restart 后即可调用 10 个 tools（见下面 Tools 表）。

---

## 定位

跟现有产品的差别：

| 维度 | Notion / Obsidian / Logseq | 普通 RAG | **memex** |
|------|---|---|---|
| 主体 | 你用工具 | 给你 chunks | 你问专家 |
| 维护 | 手动 | 自动索引 | LLM 主动 digest + 维护一致性 |
| 输出 | wiki 页面 | retrieved 片段 | **专家综合的答案** |
| 集成 | 自家 app | 嵌入你的 app | **MCP，任何 agent 接入** |

跟 Karpathy [LLM wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 的关系：基于他的三铁律（concepts first / sources feed concepts / no source-specific pages）+ 把 wiki 升级成可被任何 agent 消费的 **expert agent service**。

## Tools（MCP 暴露 10 个）

| Tool | 用途 |
|------|------|
| `wiki_guide` | agent 自学，调任何 tool 前先看 |
| **`wiki_ask_expert(question)`** ⭐ | **问 memex 这个专家一个问题**——拿综合答案（不污染你 context） |
| `wiki_ingest_source(source)` | digest 一份 docs/X.md → 写 .staging/（不动 production） |
| `wiki_apply_staging(source, apply=True)` | 把 staging 写到 production + git commit |
| `wiki_search(query, budget)` | 原料级 grep wiki |
| `wiki_read(paths)` | 整页 markdown |
| `wiki_index(filter)` | INDEX 目录 |
| `wiki_status(target)` | kanban / lifecycle / source-of |
| `wiki_pending` | search miss 队列（被 caller 触发的 enrich 需求）|
| `wiki_pending_applies` | watcher 产出 staging 待 apply 队列 |

## 不变量（design invariants）

1. **单租户分散部署** —— 每人跑自己一份；知识是私人 asset
2. **LLM as glue, not orchestrator** —— LLM 是被代码调用的 function，代码 driver；**不是 agent system，不引 agent framework**
3. **Expert agent service, not retrieval helper** —— wiki 是 memex 的 long-term memory；caller 拿到的是专家答复
4. **Provider 中立** —— OpenAI-compat endpoint 即可
5. **永远不 git push** —— commit 到 wiki repo 仅在本地；push 由 owner 决定

## 架构

```
service/
├── config.py         # yaml + env 配置加载
├── prompts.py        # digest / reviewer / expert 3 个 system prompt
├── llm.py            # OpenAI-compat client wrapper
├── retriever.py      # grep 候选页 + 构造 LLM prompt
├── validator.py      # JSON parse + schema check + 三铁律 lint
├── staging.py        # apply edits → .staging/ (mirror of wiki/)
├── digest.py         # digest 入口（含 retry + reviewer pass）
├── reviewer.py       # 2nd LLM call 审计 digest 输出
├── git_ops.py        # promote staging → production + commit
├── query.py          # expert agent 综合答案
├── watcher.py        # file watcher (raw/ → auto pipeline)
├── mcp_server.py     # 10 MCP tools，端口 18766
└── __main__.py       # CLI: python -m service digest|commit
```

## Stack

- Python 3.11+
- **openai** SDK（OpenAI-compat client）
- **fastmcp** (MCP server)
- **watchdog** (file system watcher)
- **pyyaml** (config)
- 标准库 subprocess / multiprocessing / threading
- 不引：LangGraph / CrewAI / LangChain / Celery / Redis

## What's NOT in memex（边界）

- ❌ Web research / 搜索引擎（caller agent 自己干）
- ❌ Dialogue / chat UI（client 干）
- ❌ 任务编排 / orchestration（client 干）
- ❌ 多 user / 团队协作（永远单租户）
- ❌ Vector DB / embedding search（grep + 概念组织已足够 personal scale）
- ❌ Auto-push 到 GitHub（你手动 push）

## Configuration

参考 `memex.yaml.example`。两种 override 方式：
- **yaml file**: `~/.config/memex/memex.yaml` 或 `<repo>/memex.yaml`
- **env vars**: `MEMEX_WIKI_PATH` / `MEMEX_BASE_URL` / `MEMEX_API_KEY` /
  `MEMEX_DEFAULT_MODEL` / `MEMEX_MCP_PORT` / `MEMEX_MCP_HOST`

env > yaml > 内置默认值。

## Roadmap

```
✅ P0  spike (mimo digest 能力 verified)
✅ P1  digest pipeline (module + retry + reviewer + git commit)
✅ P2  MCP entry + 10 tools + file watcher + expert agent reframe
✅ P4  config 抽象 + Docker + 文档（now）
⏳ P3  并发 digest (multiprocessing) — performance optimization
⏳ P5  开源发布
```

## 历史 / 致敬

- **Vannevar Bush** *As We May Think* (1945) —— "memex" 概念源头
- **Andrej Karpathy** [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) —— 三铁律 + 通过 wiki 替代传统 RAG

## License

TBD（开源前定，目前内部使用）。
