"""浏览器 OAuth 登录：封装官方 codebuddy-agent-sdk 的 authenticate()。

重要：本模块只负责发起官方登录流程。用户在浏览器里用**自己的**账号授权，
凭证由官方 CLI 写入用户本机，本项目不接触、不保存、不分发凭证内容。
"""

from __future__ import annotations

import asyncio
import sys
import webbrowser


class LoginError(RuntimeError):
    pass


def _sdk_missing() -> bool:
    try:
        import codebuddy_agent_sdk  # noqa: F401
        return False
    except ImportError:
        return True


async def _async_login(timeout: float, open_browser: bool) -> str:
    from codebuddy_agent_sdk import authenticate  # 延迟导入，便于给出友好报错

    flow = await authenticate(timeout=timeout)
    url = getattr(flow, "auth_url", "") or ""

    if not url:
        # 已经登录：直接完成
        result = await flow
        info = getattr(result, "userinfo", None)
        name = getattr(info, "user_nickname", "") or getattr(info, "user_name", "")
        return f"已处于登录状态{('：' + name) if name else ''}，无需重复登录。"

    print("\n请在浏览器中完成授权（使用你自己的 WorkBuddy / CodeBuddy 账号）：")
    print("  " + url)
    if open_browser:
        try:
            webbrowser.open(url)
            print("  已尝试自动打开浏览器；若没弹出，请手动复制上面的地址。")
        except Exception:
            print("  无法自动打开浏览器，请手动复制上面的地址。")
    print("\n等待授权完成……（最长 %d 秒）" % int(timeout))

    result = await flow
    info = getattr(result, "userinfo", None)
    name = getattr(info, "user_nickname", "") or getattr(info, "user_name", "")
    return f"登录成功{('：' + name) if name else ''}。凭证已由官方客户端保存在本机。"


def do_login(timeout: float = 300.0, open_browser: bool = True) -> str:
    """执行登录，返回给用户看的结果说明（不含任何 token）。"""
    if _sdk_missing():
        raise LoginError(
            "缺少官方 SDK。请先安装依赖：\n"
            "    pip install -e .\n"
            "（会自动安装 codebuddy-agent-sdk）"
        )
    try:
        if sys.platform == "win32":
            # Windows 上 asyncio 默认策略对子进程支持有限，显式使用 selector 事件循环
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        return asyncio.run(_async_login(timeout, open_browser))
    except KeyboardInterrupt:
        raise LoginError("已取消登录。")
    except Exception as exc:
        raise LoginError(f"登录失败：{exc}") from exc
