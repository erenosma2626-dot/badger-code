"""LLM_MAX_TOKENS default setting and override tests.

v0.5.1: LLM_MAX_TOKENS default adjusted from 8192 to 4096 for cost
optimization while retaining sufficient headroom for responses. Env var
override must still work.
"""

import os

import pytest

from agent.llm import LLMClient


def test_max_tokens_defaults_to_4096(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    client = LLMClient()
    assert client.max_tokens == 4096


def test_max_tokens_env_var_override_still_works(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    client = LLMClient()
    assert client.max_tokens == 8192
