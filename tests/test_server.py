"""HTTP 层测试：在进程内起服务，验证路由与 OpenAI 兼容结构。"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from wbapi import server as s
from wbapi.registry import default_provider, provider_names


@pytest.fixture(scope="module")
def httpd():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()


def _request(httpd, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    if body is None:
        conn.request(method, path)
    else:
        conn.request(method, path, body=json.dumps(body).encode("utf-8"),
                     headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read().decode("utf-8", "replace")
    status = resp.status
    conn.close()
    return status, data


def test_model_list_override(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_MODELS", "m1, m2 ,m3")
    assert s.model_list() == ["m1", "m2", "m3"]


def test_resolve_route_known_provider():
    assert s.resolve_route("workbuddy/deepseek-v4.1-flash") == (
        "workbuddy", "deepseek-v4.1-flash")


def test_resolve_route_default_without_prefix():
    d = default_provider()
    assert s.resolve_route("deepseek-v4.1-flash") == (d, "deepseek-v4.1-flash")
    assert s.resolve_route(None) == (d, "")


def test_resolve_route_keeps_fcc_custom_prefix():
    """FCC 的 custom_xxx/model 不应被误当成 provider。"""
    d = default_provider()
    assert s.resolve_route("custom_abc123/hy4std") == (d, "custom_abc123/hy4std")


def test_all_models_are_prefixed():
    entries = s.all_models()
    assert entries and all("/" in m["id"] for m in entries)
    assert all(m["owned_by"] in provider_names() for m in entries)


def test_health_and_root(httpd):
    status, data = _request(httpd, "GET", "/health")
    assert status == 200 and json.loads(data)["ok"] is True

    status, data = _request(httpd, "GET", "/")
    obj = json.loads(data)
    assert status == 200 and obj["service"] == "agent-gateway"
    assert "/v1/chat/completions" in obj["endpoints"]
    assert "workbuddy" in obj["providers"]


def test_models_endpoint(httpd):
    status, data = _request(httpd, "GET", "/v1/models")
    obj = json.loads(data)
    assert status == 200 and obj["object"] == "list"
    assert obj["data"] and all("id" in m for m in obj["data"])


def test_unknown_path(httpd):
    status, data = _request(httpd, "GET", "/nope")
    assert status == 404 and "error" in json.loads(data)


def test_bad_json(httpd):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    conn.request("POST", "/v1/chat/completions", body=b"not json",
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 400
    conn.close()


def test_chat_without_credentials_returns_502(httpd):
    """没有登录态时给出清晰 502，而不是崩溃或挂起。"""
    status, data = _request(httpd, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": False,
    })
    obj = json.loads(data)
    # 本机若有登录态会实际调用云端（不可控），因此只接受 200 或 502
    assert status in (200, 502)
    if status == 502:
        assert "error" in obj and obj["error"]["type"] == "api_error"
