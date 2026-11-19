"""Provider 抽象层与注册表测试：为接入豆包/千问等 agent 打基础。"""

from __future__ import annotations

import pytest

from wbapi.base import Provider, ProviderStatus
from wbapi.registry import default_provider, get_provider, provider_names, register


def test_default_is_workbuddy():
    assert default_provider() == "workbuddy"
    assert get_provider().name == "workbuddy"


def test_workbuddy_registered():
    assert "workbuddy" in provider_names()
    p = get_provider("workbuddy")
    assert p.label and "WorkBuddy" in p.label


def test_get_provider_case_insensitive():
    assert get_provider("WORKBUDDY").name == "workbuddy"


def test_unknown_provider_raises():
    with pytest.raises(ValueError) as exc:
        get_provider("doubao-not-registered")
    assert "未知的 provider" in str(exc.value)


def test_can_register_a_new_provider():
    """模拟未来接入一个新 agent：注册后即可按名字取回。"""

    class FakeProvider(Provider):
        name = "fake-agent"
        label = "Fake Agent"

        def login(self, timeout=300.0, open_browser=True) -> str:
            return "ok"

        def status(self) -> ProviderStatus:
            return ProviderStatus(False, detail="未登录")

        def list_models(self) -> list[str]:
            return ["fake-model"]

        def stream_chat(self, model, messages):
            yield "hi"

    register(FakeProvider())
    assert "fake-agent" in provider_names()
    assert get_provider("fake-agent").list_models() == ["fake-model"]
