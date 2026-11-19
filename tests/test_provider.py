"""模型名规整、消息提取、SSE 解析等纯逻辑测试。"""

from __future__ import annotations

from wbapi import provider as p


def test_normalize_model_known():
    available = ["deepseek-v4.1-flash", "hy4std"]
    assert p.normalize_model("hy4std", available) == "hy4std"
    assert p.normalize_model("custom_abc123/hy4std", available) == "hy4std"


def test_normalize_model_unknown_falls_back():
    available = ["deepseek-v4.1-flash", "hy4std"]
    assert p.normalize_model("does-not-exist", available) == "deepseek-v4.1-flash"


def test_normalize_model_empty():
    assert p.normalize_model(None, ["a", "b"]) == "a"
    assert p.normalize_model("", []) == p.DEFAULT_MODEL


def test_build_messages_filters_and_flattens():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": [{"type": "text", "text": "你好"}]},
        {"role": "tool", "content": "ignore me"},
        {"role": "assistant", "content": "  "},
    ]
    assert p.build_messages(messages) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "你好"},
    ]


def test_iter_text_parses_sse_stream():
    raw = "\n".join([
        'data: {"choices":[{"delta":{"content":"你"}}]}',
        "data: malformed",
        'data: {"choices":[{"delta":{"content":"好"}}]}',
        "data: [DONE]",
        "",
    ])
    assert list(p._iter_text(raw)) == ["你", "好"]
