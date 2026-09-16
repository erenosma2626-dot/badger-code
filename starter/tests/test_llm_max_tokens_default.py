"""v0.4.1 madde 2: LLM_MAX_TOKENS default raised from 2048 to 8192 so a
long write_file payload / regex doesn't get cut off mid-generation
(finish_reason="length"), which previously caused the model to loop
re-generating the same truncated content (chess-best-move/2RrorEW,
regex-log/FZorHju trials). Env var override must still work.
"""

import os

import pytest

from agent.llm import LLMClient


def test_max_tokens_defaults_to_8192(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    client = LLMClient()
    assert client.max_tokens == 8192


def test_max_tokens_env_var_override_still_works(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    client = LLMClient()
    assert client.max_tokens == 4096
