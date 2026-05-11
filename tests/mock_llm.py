"""Mock OpenAI client for unit tests.

Usage in test:
    monkeypatch.setattr("service.llm.get_client", lambda: MockClient([response_text_1, response_text_2]))

Each LLM call pops the next response from the list.
"""
from __future__ import annotations

from typing import Any


class _MockMessage:
    def __init__(self, content: str):
        self.content = content


class _MockChoice:
    def __init__(self, content: str):
        self.message = _MockMessage(content)


class _MockResponse:
    def __init__(self, content: str):
        self.choices = [_MockChoice(content)]


class _MockCompletions:
    def __init__(self, parent):
        self.parent = parent

    def create(self, **kwargs):
        return self.parent._next_response(**kwargs)


class _MockChat:
    def __init__(self, parent):
        self.completions = _MockCompletions(parent)


class MockClient:
    """In-memory mock that mimics openai.OpenAI just enough for service.llm.call_llm."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.chat = _MockChat(self)

    def _next_response(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise RuntimeError(
                f"Mock ran out of responses (call #{len(self.calls)})"
            )
        return _MockResponse(self.responses.pop(0))
