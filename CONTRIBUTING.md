# Contributing to memex

memex 是个**有 opinion 的小工具**——不是想做大而全的产品，是做"个人外置大脑 + agent 接入"这一件事做好。

## Design invariants（不会动摇的）

新 feature / PR 必须不违反：

1. **单租户分散部署** — 每人跑自己一份，不做 multi-tenant
2. **LLM as glue, not orchestrator** — LLM 是被代码调用的 function；不引 agent framework
3. **Expert agent service, not retrieval helper** — caller 拿到的是专家答复，不是 chunks
4. **Provider 中立** — OpenAI-compat endpoint 即可，不绑 Anthropic / 不绑 mimo
5. **永远不 git push** — commit 到 wiki repo 仅本地，push 由 owner 决定

## Stack 约束

- Python 3.11+，标准库优先
- 已用的运行时依赖（4 个）：`fastmcp` / `openai` / `watchdog` / `pyyaml`
- 不引：LangGraph / CrewAI / LangChain / Celery / Redis / vector DB

新依赖必须有充分理由 + 不违反 stack 哲学。

## 开发

### 装环境

```bash
git clone <fork>
cd memex
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest  # for tests
```

### 跑测试

```bash
# 简陋方式（self-contained，无依赖）：
python tests/test_validator.py
python tests/test_staging.py

# pytest 方式：
pytest tests/
```

### 改了 code 后

1. 跑测试
2. 跑一遍真 digest（消耗 1-2 mimo call）：
   ```bash
   python -m service digest <some-source.md>
   ```
3. 检查 MCP server 还能启动：
   ```bash
   python -m service.mcp_server --http  # ctrl-c 退出
   ```

## 测试覆盖优先级

**P0（最关键）**：
- `service/validator.py`：JSON parse + schema check + 三铁律 lint
- `service/staging.py`：frontmatter merge + apply edits

**P1**：
- `service/git_ops.py`：dry-run / apply / commit message
- `service/retriever.py`：candidate selection（mock filesystem）

**P2**：
- LLM-dependent module（digest / reviewer / query）—— 用 mock LLM client

## Commit message convention

```
<type>(<scope>): <short summary>

<body explaining why, not what — diff shows what>
```

types: `feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `prompt` / `infra`

例子见已有 commits (`git log --oneline`).

## Issue / PR

- 现阶段是 owner 用 + 探索 feature parity，issue/PR 优先级低
- 等 v0.1 公开后再正式接受外部贡献
