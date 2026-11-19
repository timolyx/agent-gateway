"""命令行入口与帮助文本测试。"""

from __future__ import annotations

import pytest

from wbapi import __version__
from wbapi.cli import build_parser, main


def test_subcommands_registered():
    parser = build_parser()
    sub = parser._subparsers._group_actions[0].choices
    assert set(sub) == {"login", "status", "models", "providers", "serve"}


def test_no_args_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "agent-gateway" in out and "login" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_models_command(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_GATEWAY_MODELS", "a,b")
    assert main(["models"]) == 0
    assert "a" in capsys.readouterr().out


def test_providers_command(capsys):
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "workbuddy" in out and "默认" in out


def test_models_with_explicit_provider(capsys):
    assert main(["models", "-p", "workbuddy"]) == 0
    assert capsys.readouterr().out.strip()


def test_unknown_provider_returns_error(capsys):
    assert main(["models", "-p", "not-exist"]) == 1
    assert "未知的 provider" in capsys.readouterr().err
