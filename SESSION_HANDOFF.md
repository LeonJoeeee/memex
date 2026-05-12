# Session Handoff — 给新 Claude Code session 看

> 你是接管 memex 项目的新 Claude Code session。本文档 5 分钟让你 onboard。

## 项目一句话

memex = 外置大脑 / 个人知识 specialist agent service via MCP。所有 substantive
foundation 已 done，21 commits 在 GitHub。你接手 day-to-day refinement + 真用
+ 探索新方向。

仓库：https://github.com/LeonJoeeee/memex （public, MIT）。

## 先读这三个文件（顺序）

1. **README.md** — 5-min quickstart + 不变量 + 12 tools 表
2. **ARCHITECTURE.md** — 系统形态图 + 数据流 + 设计决策详解
3. **CONTRIBUTING.md** — 不变量 + stack 约束（变更前看）

跳过历史 commit log，直接看代码 + 文档。

## 当前 deployment 状态

| Service | Port | Status | 启动 |
|---|---|---|---|
| `memex-mcp.service` | 18766 | active | systemd user unit (auto-start) |
| `memex-watcher.service` | — | active | 监控 `/home/leon/llm-wiki/raw/` |

两个 systemd user service 已 enable + 跑：
```bash
systemctl --user status memex-mcp memex-watcher
journalctl --user -u memex-watcher -f   # 实时看 watcher 干啥
```

API key + base_url 走 `/home/leon/llm-wiki/tools/_env.py` legacy fallback 加载
mimo 凭据。Phase 4 已抽到 yaml + env，但当前部署仍用 legacy 兼容。

## 当前 session（你）vs 平行 session

- **平行 session**（`/home/leon/llm-wiki/`）：维护 wiki 数据本身（digest / lint /
  事故修复），他在那边跑。**不要碰** llm-wiki 数据维护，那是他的职能。
- **你（`/home/leon/memex/`）**：memex service 本身的开发 / 改进 / 真用。

明确的 boundary：
- ✅ 你改 `memex/service/` 代码、`memex/tests/`、`memex/docs`、`memex/.github/`
- ✅ 你可以测试 wiki_ask_expert 跑各种 question
- ✅ 你可以投 source 到 `raw/` 让 watcher 跑（mimo token 不愁，user 明确说了）
- ⚠️ 你**修改** `llm-wiki/wiki/*` 要走 wiki_apply_staging（不要直接 Edit）
- ⚠️ 你**不要**碰 `llm-wiki/.claude/skills/`（那是平行 session 的 skill）
- ⚠️ 你**不要**碰 `llm-wiki/tools/`（除非 memex 真需要扩展 preprocess pipeline）

## User 给的优先级方向

按 user 上次明确（截至 handoff 时）：

1. **真用 + 找 issue**——通过实际使用发现 prompt / pipeline 的 rough edges
2. **新 source 测试**：丢 raw/ 文件让 watcher 真触发，看 mimo 自动 digest 质量
3. **wiki_ask_expert 真问几个问题**，挖 retrieval / synthesis 的边界
4. **iteration**：基于实测调 prompt / config / 加新 feature

二级优先级（user 未 explicit 要求，但 Roadmap 列了）：
- P3 并发 digest（multiprocessing）
- 完善 docs（demo GIF / 更详细 examples）
- 写 CLAUDE.md 给 memex 项目（可选，给后续 session 用）

## Quick verification（onboard 完跑一遍）

```bash
cd /home/leon/memex

# 1. tests 全过
/home/leon/llm-wiki/.venv-mcp/bin/python3 -m pytest tests/ 2>&1 | tail -3
# 期待: 67 passed

# 2. MCP server 在跑
ss -tnlp 2>/dev/null | grep 18766
# 期待: LISTEN 127.0.0.1:18766

# 3. wiki_stats sanity
/home/leon/llm-wiki/.venv-mcp/bin/python3 -c "
from service.mcp_server import wiki_stats
import json
print(json.dumps(wiki_stats(), ensure_ascii=False, indent=2)[:500])
"
# 期待: total_pages ~729, by_type 含 concepts/entities

# 4. wiki_ask_expert 真调（消耗 1 mimo call, user 说不愁 token）
/home/leon/llm-wiki/.venv-mcp/bin/python3 -c "
from service.query import query_wiki
import json
r = query_wiki('一句话总结：什么是 memex', depth='quick')
print(r['answer'][:400])
"

# 5. GitHub CI 状态
gh run list -R LeonJoeeee/memex --limit 3
```

## 设计原则（绝对不能动摇）

1. **不引 agent framework** — LangGraph / CrewAI / OpenAI Agents SDK 都不要
2. **LLM as glue, not orchestrator** — 代码 driver，LLM 是被调用的 function
3. **Single-tenant** — 永远不做 multi-tenant
4. **No auto git push** — commit OK，push 要 user 手动
5. **No wiki write bypass** — 改 wiki 必经 staging + commit gate

新 feature 违反任一条 = 不做。

## Stack 约束

只用这 4 个运行时依赖：`fastmcp` / `openai` / `watchdog` / `pyyaml`（+ Python 标准库）。

加新依赖前 push back 自己：能用标准库 / 现有 4 个 dep 解决吗？

## 12 MCP tools 列表（你 expose 给 caller 的能力）

| Tool | 类别 | 用途 |
|------|------|------|
| `wiki_guide` | admin | agent 自学 |
| `wiki_ask_expert` | expert ⭐ | 专家咨询（caller 拿成品答案）|
| `wiki_ingest_source` | ingest | digest 一个 docs/X.md → staging |
| `wiki_apply_staging` | ingest | staging → production + commit |
| `wiki_search` | read | 原料级 grep |
| `wiki_read` | read | 整页 markdown |
| `wiki_index` | read | INDEX 目录 |
| `wiki_status` | read | kanban / lifecycle / source-of |
| `wiki_recent_changes` | read | 最近 git commit |
| `wiki_stats` | read | 总览数据 |
| `wiki_pending` | admin | miss 队列 |
| `wiki_pending_applies` | admin | watcher 产出 staging 待 apply 队列 |

## 几个值得 spike 的方向（按 ROI 估）

1. **找 wiki_ask_expert 的 rough edge**：问几个不同 domain 问题（finance / 物理 /
   AI），看 confidence 误判 / cite 错误 / 数字精度问题
2. **mimo 跨语言能力**：英文问题对中文 wiki，中文问题对英文片段，是否仍准确
3. **长 source ingest**：丢一本完整电子书（300+ 页）到 raw/，看 mimo 怎么处理
   超长 context（可能需要 chunked digest）
4. **prompt 工程 iterate**：发现 reviewer 不抓某类违规 → 改 prompt → 重测
5. **加 wiki_ask_expert 缓存**：相同 question + 相同 wiki 状态 → 缓存 answer
   （key 含 last_commit hash 自动 invalidate）

## 不要做（防 over-engineering）

- ❌ 加 vector DB / embedding search（grep + concept 组织足够 personal scale）
- ❌ 加 multi-tenant 支持（永远 single-tenant）
- ❌ 加 web research（caller agent 自己干）
- ❌ 加 dialogue 历史维护（client 干）
- ❌ 加 LangGraph / CrewAI 任何 agent framework
- ❌ 直接 Edit `wiki/*.md`（必经 staging）
- ❌ Auto `git push`（owner 手动）

## 联络 user

- 主用户：Leon（LeonJoeeee on GitHub，liangqiaohitsz@gmail.com）
- 平行 session 在 `/home/leon/llm-wiki/`，专管 wiki 数据
- mimo token quota 充裕（user 明确说），不必省 LLM call
- 但 commit / push 决策点要 confirm（git push 永远手动）

---

**Last updated**: 2026-05-12 by 平行 session
**Project state**: production-ready MVP，22 commits 含本 handoff
