"""Provider 注册表：把 provider 名字映射到实现实例。"""

from __future__ import annotations

from .base import Provider

_DEFAULT = "workbuddy"
_REGISTRY: dict[str, Provider] = {}
_bootstrapped = False


def register(provider: Provider) -> None:
    """注册（或覆盖）一个 provider。供内置实现与外部扩展使用。"""
    key = provider.name.strip().lower()
    if not key:
        raise ValueError("provider.name 不能为空")
    _REGISTRY[key] = provider


def _bootstrap() -> None:
    """延迟注册内置 provider，避免与 provider.py 循环导入。"""
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    from .provider import WorkBuddyProvider
    register(WorkBuddyProvider())


def provider_names() -> list[str]:
    _bootstrap()
    return sorted(_REGISTRY)


def get_provider(name: str | None = None) -> Provider:
    """按名字取 provider；未指定时返回默认 provider。"""
    key = (name or _DEFAULT).strip().lower()
    _bootstrap()
    if key not in _REGISTRY:
        raise ValueError(
            f"未知的 provider：{key}。可用：{', '.join(provider_names())}")
    return _REGISTRY[key]


def default_provider() -> str:
    return _DEFAULT
