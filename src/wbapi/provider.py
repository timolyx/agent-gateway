"""调用官方云端 /v2/chat/completions，并按 OpenAI 格式输出。

云端只接受流式请求（非流式会返回 400），因此统一用 stream=true 请求，
再把 SSE 片段聚合成文本或对外的流式响应。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .auth import do_login
from .base import Provider, ProviderStatus
from .credentials import (
    Credentials,
    find_auth_file,
    load_credentials,
    refresh_credentials,
    valid_credentials,
)

DEFAULT_MODEL = "deepseek-v4.1-flash"
TIMEOUT = 180


class ProviderError(RuntimeError):
    pass


def normalize_model(raw: str | None, available: list[str]) -> str:
    """把外部传入的模型名规整为可用 ID；兼容 custom_xxx/model 形式。"""
    if not raw:
        return DEFAULT_MODEL if DEFAULT_MODEL in available else (available[0] if available else DEFAULT_MODEL)
    mid = str(raw).strip()
    if "/" in mid:
        mid = mid.rsplit("/", 1)[-1]
    if mid in available:
        return mid
    return DEFAULT_MODEL if DEFAULT_MODEL in available else (available[0] if available else mid)


def build_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """提取 system / user / assistant 文本，忽略其它字段。"""
    out: list[dict[str, str]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        if role not in ("system", "user", "assistant"):
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        content = str(content).strip()
        if content:
            out.append({"role": role, "content": content})
    return out


def _request_sse(cred: Credentials, model: str,
                 messages: list[dict[str, str]]) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
    }, ensure_ascii=False).encode("utf-8")
    req = Request(
        cred.api_base.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + cred.access_token,
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _iter_text(raw: str) -> Iterable[str]:
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        piece = delta.get("content") or ""
        if piece:
            yield piece


def stream_text(cred: Credentials, model: str,
                messages: list[dict[str, str]]) -> Iterable[str]:
    """产出回答片段。凭证被拒绝时自动续期并重试一次。"""
    for attempt in (0, 1):
        try:
            raw = _request_sse(cred, model, messages)
        except HTTPError as exc:
            if exc.code in (401, 403) and attempt == 0:
                cred = refresh_credentials(cred)
                continue
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise ProviderError(f"云端拒绝请求（HTTP {exc.code}）：{detail}")
        except (URLError, TimeoutError) as exc:
            raise ProviderError(f"连接云端失败：{str(exc)[:120]}")
        yield from _iter_text(raw)
        return
    raise ProviderError("凭证续期后仍被拒绝，请重新运行 login。")


# ------------------------------------------------------------------
# WorkBuddy 的第一个 provider 实现。
# 以后接豆包 / 千问 / 百度搭子：照抄这个类，改 name/label 与上面四个动作，
# 再在 registry 里注册即可，命令层与服务层都不用改。
# ------------------------------------------------------------------
class WorkBuddyProvider(Provider):
    name = "workbuddy"
    label = "WorkBuddy / CodeBuddy"

    def login(self, timeout: float = 300.0, open_browser: bool = True) -> str:
        return do_login(timeout=timeout, open_browser=open_browser)

    def status(self) -> ProviderStatus:
        if find_auth_file() is None:
            return ProviderStatus(False, detail="本机未找到登录态")
        try:
            cred = load_credentials()
        except Exception as exc:
            return ProviderStatus(False, detail=str(exc))
        label = cred.user_label
        detail = ""
        if cred.expires_at:
            import time as _t
            detail = "有效期至 " + _t.strftime(
                "%Y-%m-%d %H:%M", _t.localtime(cred.expires_at))
        return ProviderStatus(True, label=label, detail=detail)

    def list_models(self) -> list[str]:
        # 复用服务层的模型清单（环境变量覆盖 / 本机缓存 / 兜底）。
        from .server import model_list
        return model_list()

    def stream_chat(self, model: str,
                    messages: list[dict[str, Any]]) -> Iterable[str]:
        cred = valid_credentials()
        return stream_text(cred, model, messages)
