"""Conversation-history compaction for the LLM call (v0.7, H1).

Faz B: input/output token ratio was 55:1 because the full history —
every receipt and every write_file body — was resent on every turn. The
agent keeps the full transcript for logging, but sends the model a view
where only the most recent ``keep_recent`` tool results are verbatim and
older ones are reduced to their facts (exit code, error, a short excerpt).
Message structure and tool_call ids are preserved so the API still sees
valid assistant/tool pairs.
"""

from __future__ import annotations

import copy
import json

_OLD_EXCERPT_CHARS = 200
_OLD_TEXT_CHARS = 300
_OLD_ARG_CHARS = 160


def _short(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[{len(text) - limit} chars omitted]"


def _compact_tool_content(content: str) -> str:
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return _short(content or "", _OLD_EXCERPT_CHARS)
    if not isinstance(data, dict):
        return _short(content, _OLD_EXCERPT_CHARS)
    out = {"old_result": True}
    for key in ("tool", "exit_code", "timed_out", "error", "output_ref",
                "content_bytes", "total_lines", "acknowledged", "reason"):
        if data.get(key) not in (None, "", [], False):
            out[key] = data[key]
    for key in ("stdout_tail", "stderr_tail"):
        if data.get(key):
            out[key] = _short(data[key], _OLD_EXCERPT_CHARS)
    return json.dumps(out, separators=(",", ":"))


def _compact_tool_calls(tool_calls: list[dict]) -> list[dict]:
    out = []
    for tc in tool_calls:
        tc = copy.deepcopy(tc)
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (TypeError, ValueError):
            args = None
        if isinstance(args, dict):
            for key, val in list(args.items()):
                if isinstance(val, str) and len(val) > _OLD_ARG_CHARS:
                    args[key] = _short(val, _OLD_ARG_CHARS)
            fn["arguments"] = json.dumps(args)
        out.append(tc)
    return out


def compact_messages(messages: list[dict], keep_recent: int) -> list[dict]:
    """Return a compacted copy of ``messages`` (the input is not modified).

    The first two messages (system prompt, task) and everything from the
    ``keep_recent``-th most recent tool result onward stay verbatim.
    """
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if len(tool_idx) <= keep_recent:
        return list(messages)
    if keep_recent <= 0:
        cut = len(messages)
    else:
        # step back to the assistant turn that issued the first kept result
        cut = tool_idx[-keep_recent]
        while cut > 2 and messages[cut].get("role") != "assistant":
            cut -= 1

    out: list[dict] = []
    for i, m in enumerate(messages):
        if i < 2 or i >= cut:
            out.append(m)
            continue
        role = m.get("role")
        if role == "tool":
            out.append({**m, "content": _compact_tool_content(m.get("content") or "")})
        elif role == "assistant":
            new = {**m, "content": _short(m.get("content") or "", _OLD_TEXT_CHARS)}
            if m.get("tool_calls"):
                new["tool_calls"] = _compact_tool_calls(m["tool_calls"])
            out.append(new)
        else:
            out.append({**m, "content": _short(m.get("content") or "", _OLD_TEXT_CHARS)})
    return out
