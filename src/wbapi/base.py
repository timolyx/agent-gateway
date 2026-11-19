"""Provider 抽象接口。

每个 agent（WorkBuddy / 豆包 / 千问 ...）实现同一套接口；网关与 CLI
只依赖本模块，不关心具体 agent 的实现细节。新增一个 agent = 新增一个
实现 Provider 的模块 + 在 registry 注册，命令与主服务都不用改。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderStatus:
    """登录状态，绝不包含 token。"""

    logged_in: bool
    label: str = ""     # 账号昵称
    detail: str = ""    # 补充说明（有效期或错误原因）


class Provider(ABC):
    """一个可以被网关暴露成 OpenAI API 的 agent。"""

    name: str = ""   # 机器名：用于 -p 参数与模型前缀，如 workbuddy
    label: str = ""  # 展示名：如 WorkBuddy / CodeBuddy

    @abstractmethod
    def login(self, timeout: float = 300.0, open_browser: bool = True) -> str:
        """发起登录，返回给用户看的说明（不含 token）。"""

    @abstractmethod
    def status(self) -> ProviderStatus:
        """返回本机登录状态；不应抛异常。"""

    @abstractmethod
    def list_models(self) -> list[str]:
        """列出本 provider 可用的模型 ID。"""

    @abstractmethod
    def stream_chat(self, model: str,
                    messages: list[dict[str, Any]]) -> Iterable[str]:
        """流式产出回答片段。

        凭证缺失/过期抛 NoCredentials，上游拒绝抛 ProviderError。
        """
