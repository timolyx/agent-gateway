"""命令行入口：agent-gateway login | status | models | providers | serve"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .auth import LoginError
from .registry import default_provider, get_provider, provider_names
from .server import serve

HELP = """agent-gateway —— 把 WorkBuddy / CodeBuddy 订阅模型暴露为本地 OpenAI 兼容 API

用法：
  agent-gateway providers           列出所有可用 agent
  agent-gateway login -p workbuddy  在浏览器里授权某个 agent（只需一次）
  agent-gateway status -p workbuddy 查看该 agent 登录状态（不显示 token）
  agent-gateway models -p workbuddy 列出该 agent 的可用模型
  agent-gateway serve               启动本地 API 服务（默认 127.0.0.1:8000）

-p / --provider 可省略，默认 workbuddy。以后加豆包、千问等 agent 只需：
  agent-gateway login -p doubao
客户端用 "doubao/模型名" 即可指定走哪家。
"""


def _provider(name: str | None):
    try:
        return get_provider(name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return None


def cmd_providers(args: argparse.Namespace) -> int:
    print("可用的 agent（provider）：")
    for name in provider_names():
        p = get_provider(name)
        mark = "  (默认)" if name == default_provider() else ""
        print(f"  {name:<12} {p.label}{mark}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    p = _provider(args.provider)
    if p is None:
        return 1
    try:
        print(p.login(timeout=args.timeout, open_browser=not args.no_browser))
        return 0
    except LoginError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    p = _provider(args.provider)
    if p is None:
        return 1
    st = p.status()
    print(f"agent：{p.name}（{p.label}）")
    if not st.logged_in:
        print("状态：未登录")
        if st.detail:
            print(st.detail)
        print(f"请先运行：agent-gateway login -p {p.name}")
        return 1
    print("状态：已登录")
    if st.label:
        print(f"账号：{st.label}")
    if st.detail:
        print(st.detail)
    return 0


def _fmt(ts: float) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "未知"


def cmd_models(args: argparse.Namespace) -> int:
    p = _provider(args.provider)
    if p is None:
        return 1
    for m in p.list_models():
        print(m)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    serve(host=args.host, port=args.port)
    return 0


def _add_provider_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p", "--provider", default=None,
        help=f"指定 agent，默认 {default_provider()}（见 providers 命令）")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-gateway", description=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    pp = sub.add_parser("providers", help="列出所有可用 agent")
    pp.set_defaults(func=cmd_providers)

    pl = sub.add_parser("login", help="在浏览器里用自己的账号授权登录")
    pl.add_argument("--timeout", type=float, default=300.0, help="等待授权秒数（默认 300）")
    pl.add_argument("--no-browser", action="store_true", help="不自动打开浏览器，只打印地址")
    _add_provider_arg(pl)
    pl.set_defaults(func=cmd_login)

    ps = sub.add_parser("status", help="查看本机登录状态（不显示 token）")
    _add_provider_arg(ps)
    ps.set_defaults(func=cmd_status)

    pm = sub.add_parser("models", help="列出可用模型")
    _add_provider_arg(pm)
    pm.set_defaults(func=cmd_models)

    pv = sub.add_parser("serve", help="启动本地 API 服务")
    pv.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    pv.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    pv.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        print(HELP)
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
