"""memex — 外置大脑 / personal knowledge specialist agent service.

Phase 1 modules:
- prompts:   system prompts (digest / reviewer / lint / query)
- llm:       LLM client wrapper (mimo / openai-compat)
- digest:    digest pipeline (P1.1) [TODO]
- reviewer:  reviewer pass (P1.2) [TODO]
- validator: deterministic schema check (P1.1) [TODO]
- staging:   write to .staging/ (P1.1) [TODO]
- git_ops:   real wiki write + commit (P1.3) [TODO]
"""

__version__ = "0.0.1-spike"
