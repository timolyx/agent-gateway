"""本地 OpenAI 兼容 HTTP 服务。

暴露：
  GET  /v1/models            模型列表
  POST /v1/chat/completions  对话（支持 stream=true 的 SSE）
  GET  /health               健康检查（不触碰凭证）

任何能填写「OpenAI 兼容 Base URL」的客户端都可以接入：
    http://127.0.0.1:8000/v1
"""

from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .credentials import NoCredentials, cached_model_catalog
from .provider import ProviderError, build_messages, normalize_model
from .registry import default_provider, get_provider, provider_names

# 兜底模型清单：官方客户端缓存不可用时仍可用。可用环境变量覆盖。
FALLBACK_MODELS = [
    "fast-model", "balanced-model", "deep-model",
    "hy4std", "hy4flash-free", "hy4flash",
    "deepseek-v4.1-flash", "glm-5.3", "glm-5.3-flash", "glm-5.2",
    "space-bunny", "minimax-m3.1-flash", "kimi-k3.1-pro", "kimi-k2.8-preview",
    "deepseek-v4-pro", "step-5-preview", "mimo-v2.6-pro",
]


def model_list() -> list[str]:
    override = os.environ.get("AGENT_GATEWAY_MODELS", "")
    if override:
        return [m.strip() for m in override.split(",") if m.strip()]
    cached = cached_model_catalog()
    return cached or FALLBACK_MODELS


def resolve_route(raw: str | None) -> tuple[str, str]:
    """把外部模型名拆成 (provider, bare_model)。

    规则：
      - ``doubao/doubao-pro`` → ("doubao", "doubao-pro")  已知 provider 前缀
      - ``custom_abc/model``  → (默认, "custom_abc/model")  FCC 前缀，交由
        provider 内部的 normalize_model 去掉最后一截
      - ``deepseek-v4.1-flash`` → (默认, 原名)
      - 空 → (默认, "")
    """
    known = set(provider_names())
    mid = str(raw or "").strip()
    if "/" in mid:
        prefix, rest = mid.split("/", 1)
        if prefix in known and rest:
            return prefix, rest
    return default_provider(), mid


def all_models() -> list[dict[str, Any]]:
    """汇总所有 provider 的模型，id 带 ``provider/`` 前缀。"""
    now = int(time.time())
    out: list[dict[str, Any]] = []
    for name in provider_names():
        provider = get_provider(name)
        for mid in provider.list_models():
            out.append({
                "id": f"{name}/{mid}", "object": "model",
                "created": now, "owned_by": name,
            })
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agent-gateway/" + __version__

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    # ---- 响应工具 ----
    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse_data(self, obj: dict) -> None:
        self.wfile.write(
            ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")
        )
        self.wfile.flush()

    def _path(self) -> str:
        return (self.path or "/").split("?", 1)[0].rstrip("/") or "/"

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = self._path()
        if path in ("/health",):
            return self._json({"ok": True, "service": "agent-gateway",
                               "providers": provider_names()})
        if path == "/":
            return self._json({
                "service": "agent-gateway",
                "version": __version__,
                "providers": provider_names(),
                "endpoints": ["/v1/models", "/v1/chat/completions", "/health"],
            })
        if path in ("/v1/models", "/models"):
            return self._json({"object": "list", "data": all_models()})
        return self._json(
            {"error": {"message": f"路径不存在：{path}", "type": "invalid_request"}}, 404)

    def do_POST(self) -> None:
        path = self._path()
        if path not in ("/v1/chat/completions", "/chat/completions"):
            return self._json(
                {"error": {"message": f"路径不存在：{path}", "type": "invalid_request"}}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            return self._json(
                {"error": {"message": f"请求不是合法 JSON：{exc}",
                           "type": "invalid_request"}}, 400)

        models = model_list()
        provider_name, bare = resolve_route(req.get("model"))
        model = normalize_model(bare, models)
        messages = build_messages(req.get("messages", []))
        stream = bool(req.get("stream"))
        cid = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())

        if not messages:
            return self._json(
                {"error": {"message": "没有收到提问内容", "type": "invalid_request"}}, 400)

        opened = False
        try:
            provider = get_provider(provider_name)
            pieces: list[str] = []
            for piece in provider.stream_chat(model, messages):
                pieces.append(piece)
                if stream:
                    if not opened:
                        self._sse_start()
                        opened = True
                        self._sse_data({
                            "id": cid, "object": "chat.completion.chunk",
                            "created": created, "model": model,
                            "choices": [{"index": 0,
                                         "delta": {"role": "assistant"},
                                         "finish_reason": None}],
                        })
                    self._sse_data({
                        "id": cid, "object": "chat.completion.chunk",
                        "created": created, "model": model,
                        "choices": [{"index": 0, "delta": {"content": piece},
                                     "finish_reason": None}],
                    })
        except (NoCredentials, ProviderError) as exc:
            msg = str(exc)
            if stream and opened:
                self._sse_data({"error": {"message": msg, "type": "api_error"}})
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return
            return self._json(
                {"error": {"message": msg, "type": "api_error"}}, 502)
        except Exception as exc:
            msg = f"服务内部错误：{exc}"
            if stream and opened:
                self._sse_data({"error": {"message": msg, "type": "api_error"}})
                return
            return self._json(
                {"error": {"message": msg, "type": "api_error"}}, 500)

        answer = "".join(pieces)
        if stream:
            if not opened:
                self._sse_start()
            self._sse_data({
                "id": cid, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            })
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        return self._json({
            "id": cid, "object": "chat.completion", "created": created,
            "model": model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": answer},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"agent-gateway 已启动：http://{host}:{port}/v1")
    print("按 Ctrl+C 停止。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        httpd.shutdown()
