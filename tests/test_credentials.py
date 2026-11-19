"""凭证解析、端点白名单、续期状态等纯逻辑测试（不涉及真实 token）。"""

from __future__ import annotations

import time

import pytest

from wbapi import credentials as c


def test_parse_valid_payload():
    payload = {
        "auth": {
            "accessToken": "dummy-access",
            "refreshToken": "dummy-refresh",
            "expiresAt": 9_990_000_000_000,   # 毫秒
            "domain": "codebuddy.cn",
        },
        "account": {"nickname": "tester", "uid": "123"},
    }
    cred = c._parse(payload, source="unit-test")
    assert cred is not None
    assert cred.access_token == "dummy-access"
    assert cred.refresh_token == "dummy-refresh"
    assert cred.expires_at == pytest.approx(9_990_000_000.0)
    assert cred.user_label == "tester"
    assert cred.source == "unit-test"


@pytest.mark.parametrize("payload", [
    {},
    {"auth": {}},
    {"auth": {"accessToken": ""}},
    {"account": {"nickname": "x"}},
])
def test_parse_invalid_payload(payload):
    assert c._parse(payload) is None


def test_as_float_handles_seconds_and_millis():
    assert c._as_float(1_700_000_000) == pytest.approx(1_700_000_000.0)
    assert c._as_float(1_700_000_000_000) == pytest.approx(1_700_000_000.0)
    assert c._as_float("bad") == 0.0
    assert c._as_float(None) == 0.0


def test_expiry_and_refresh_flags():
    now = time.time()
    cred = c.Credentials(
        access_token="x",
        expires_at=now - 1,          # 已过期
        refresh_token="r",
        refresh_expires_at=now + 3600,
    )
    assert cred.is_expired() is True
    assert cred.can_refresh() is True

    no_refresh = c.Credentials(access_token="x", expires_at=now + 9999)
    assert no_refresh.is_expired() is False
    assert no_refresh.can_refresh() is False


@pytest.mark.parametrize("url,expected", [
    ("https://copilot.tencent.com/v2", True),
    ("https://www.codebuddy.ai/v2", True),
    ("http://copilot.tencent.com/v2", False),   # 非 HTTPS
    ("https://evil.com/v2", False),             # 非白名单主机
    ("not-a-url", False),
])
def test_trusted_endpoint(url, expected):
    assert c._is_trusted_endpoint(url) is expected


def test_resolve_api_base_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_BASE_URL", "https://example.test/api/")
    assert c.resolve_api_base() == "https://example.test/api/v2"


def test_resolve_api_base_internal_env(monkeypatch):
    monkeypatch.delenv("AGENT_GATEWAY_BASE_URL", raising=False)
    monkeypatch.setenv("CODEBUDDY_INTERNET_ENVIRONMENT", "internal")
    assert c.resolve_api_base() == c.INTERNAL_ENDPOINT + "/v2"


def test_find_auth_file_override(monkeypatch, tmp_path):
    fake = tmp_path / "auth.info"
    fake.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AGENT_GATEWAY_AUTH_FILE", str(fake))
    assert c.find_auth_file() == fake

    monkeypatch.setenv("AGENT_GATEWAY_AUTH_FILE", str(tmp_path / "missing.info"))
    assert c.find_auth_file() is None
