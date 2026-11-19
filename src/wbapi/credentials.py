"""读取本机 CodeBuddy / WorkBuddy 登录态，并在过期前自动续期。

登录态由官方 IDE 插件 / CLI 在浏览器 OAuth 成功后写入磁盘，本模块只读它，
不创建、不复制、不上传任何凭证。文件路径与解析规则与官方客户端保持一致。
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

# 官方共享登录文件名与子路径
AUTH_FILE_NAME = "Tencent-Cloud.coding-copilot.info"
AUTH_SUBPATH = ("CodeBuddyExtension", "Data", "Public", "auth")

# 官方端点（国内 / 海外）
OVERSEAS_ENDPOINT = "https://www.codebuddy.ai"
INTERNAL_ENDPOINT = "https://copilot.tencent.com"
API_PATH_PREFIX = "/v2"
INTERNAL_DOMAIN_HINTS = ("codebuddy.cn", "workbuddy.cn", "copilot.tencent.com")

REFRESH_PATH = "/v2/auth/token/refresh"
ACCOUNTS_PATH = "/v2/accounts"
EXPIRY_SKEW = 300.0  # 提前 5 分钟续期

# 本地缓存的产品配置（端点 + 模型目录）
_PRODUCT_CACHE_DIR = Path.home() / ".codebuddy" / "local_storage"
_TRUSTED_HOSTS = frozenset(
    h for h in (urlsplit(OVERSEAS_ENDPOINT).hostname,
                urlsplit(INTERNAL_ENDPOINT).hostname) if h
)


class NoCredentials(RuntimeError):
    """本机没有可用的登录态，需要用户先运行 login。"""


@dataclass(frozen=True)
class Credentials:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    refresh_expires_at: float = 0.0
    user_id: str = ""
    user_label: str = ""
    domain: str = ""
    source: str = ""

    @property
    def api_base(self) -> str:
        return resolve_api_base(self.domain)

    def is_expired(self, skew: float = EXPIRY_SKEW) -> bool:
        return bool(self.expires_at) and time.time() >= self.expires_at - skew

    def can_refresh(self) -> bool:
        if not self.refresh_token:
            return False
        if not self.refresh_expires_at:
            return True
        return time.time() < self.refresh_expires_at


# ---------- 路径搜索 ----------

def _search_dirs() -> list[Path]:
    """官方 CLI 使用的三处凭证目录（按平台）。"""
    home = Path.home()
    roots: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(Path(local))
        roots.append(home / "AppData" / "Local")
    elif sys.platform == "darwin":
        roots.append(home / "Library" / "Application Support")
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            roots.append(Path(xdg))
        roots.append(home / ".local" / "share")
    return [r.joinpath(*AUTH_SUBPATH) for r in roots]


def find_auth_file() -> Path | None:
    override = os.environ.get("AGENT_GATEWAY_AUTH_FILE")
    if override:
        p = Path(os.path.expanduser(override))
        return p if p.is_file() else None
    for d in _search_dirs():
        candidate = d / AUTH_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def _as_float(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    # 官方以毫秒存储时间戳
    return n / 1000.0 if n > 1e11 else n


# ---------- 解析 ----------

def _parse(payload: dict[str, Any], source: str = "") -> Credentials | None:
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return None
    token = auth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    account = payload.get("account")
    account = account if isinstance(account, dict) else {}
    label = ""
    for key in ("nickname", "uin", "uid"):
        if account.get(key):
            label = str(account[key])
            break
    return Credentials(
        access_token=token,
        refresh_token=str(auth.get("refreshToken") or ""),
        expires_at=_as_float(auth.get("expiresAt")),
        refresh_expires_at=_as_float(auth.get("refreshExpiresAt")),
        user_id=str(account.get("uid") or ""),
        user_label=label,
        domain=str(auth.get("domain") or ""),
        source=source,
    )


def load_credentials() -> Credentials:
    """从本机磁盘读取登录态；找不到时抛出 NoCredentials。"""
    path = find_auth_file()
    if path is None:
        raise NoCredentials(
            "本机没有找到 WorkBuddy / CodeBuddy 登录态。请先运行：\n"
            "    agent-gateway login -p workbuddy\n"
            "在浏览器中用你自己的账号完成授权。"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NoCredentials(f"登录态文件无法解析：{exc}") from exc
    cred = _parse(payload, source=str(path)) if isinstance(payload, dict) else None
    if cred is None:
        raise NoCredentials("登录态文件里没有 accessToken，请在客户端重新登录。")
    return cred


# ---------- 端点与模型目录 ----------

def _iter_cached_configs() -> list[dict[str, Any]]:
    """解码 CLI 缓存的产品配置（可能是 gzip+base64 包裹）。"""
    if not _PRODUCT_CACHE_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(_PRODUCT_CACHE_DIR.glob("entry_*.info")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, str):
            continue
        try:
            decoded = json.loads(gzip.decompress(base64.b64decode(raw)).decode("utf-8"))
        except Exception:
            continue
        if isinstance(decoded, dict):
            out.append(decoded)
    return out


def _is_trusted_endpoint(endpoint: str) -> bool:
    """只接受官方 HTTPS 端点，防止 token 被送往任意主机。"""
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    return parts.scheme == "https" and (parts.hostname or "") in _TRUSTED_HOSTS


def resolve_api_base(domain: str = "") -> str:
    """解析云端 /v2 根地址。"""
    override = os.environ.get("AGENT_GATEWAY_BASE_URL")
    if override:
        base = override.rstrip("/")
        return base if base.endswith(API_PATH_PREFIX) else base + API_PATH_PREFIX

    env = (os.environ.get("CODEBUDDY_INTERNET_ENVIRONMENT") or "").strip().lower()
    if env in ("internal", "ioa"):
        return INTERNAL_ENDPOINT + API_PATH_PREFIX

    for config in _iter_cached_configs():
        endpoint = config.get("endpoint")
        if isinstance(endpoint, str) and _is_trusted_endpoint(endpoint):
            return endpoint.rstrip("/") + API_PATH_PREFIX

    hint = domain.lower()
    if any(m in hint for m in INTERNAL_DOMAIN_HINTS):
        return INTERNAL_ENDPOINT + API_PATH_PREFIX
    return OVERSEAS_ENDPOINT + API_PATH_PREFIX


def cached_model_catalog() -> list[str]:
    """读取本机缓存里记录的模型 ID 列表。"""
    models: list[str] = []
    for config in _iter_cached_configs():
        for entry in config.get("models") or []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                mid = entry["id"]
                if mid and mid not in models:
                    models.append(mid)
    return models


# ---------- 刷新 ----------

def _post_json(url: str, obj: dict[str, Any], token: str, timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(obj).encode("utf-8")
    req = Request(url, data=data, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def refresh_credentials(cred: Credentials) -> Credentials:
    """用 refreshToken 换取新的 accessToken，返回新凭证。

    刷新由官方云端完成；新 token 写回原登录文件，供官方客户端与本项目共用。
    """
    if not cred.refresh_token:
        raise NoCredentials("登录态没有 refreshToken，需要重新登录。")
    if cred.refresh_expires_at and time.time() >= cred.refresh_expires_at:
        raise NoCredentials("登录态的续期资格已过期，需要重新登录。")

    base = cred.api_base.rstrip("/")
    root = base[:-len(API_PATH_PREFIX)] if base.endswith(API_PATH_PREFIX) else base
    payload = _post_json(
        root + REFRESH_PATH,
        {"refreshToken": cred.refresh_token},
        cred.access_token,
    )
    auth = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(auth, dict) and isinstance(auth.get("auth"), dict):
        auth = auth["auth"]
    if not isinstance(auth, dict):
        auth = payload if isinstance(payload, dict) else {}
    token = auth.get("accessToken")
    if not isinstance(token, str) or not token:
        raise NoCredentials("续期没有返回新的 accessToken，需要重新登录。")

    updated = replace(
        cred,
        access_token=token,
        refresh_token=str(auth.get("refreshToken") or cred.refresh_token),
        expires_at=_as_float(auth.get("expiresAt")) or cred.expires_at,
        refresh_expires_at=_as_float(auth.get("refreshExpiresAt")) or cred.refresh_expires_at,
    )

    # 把刷新后的 token 写回官方登录文件，保持与官方客户端一致
    path = find_auth_file()
    if path is not None:
        try:
            payload_out = json.loads(path.read_text(encoding="utf-8"))
            auth_out = payload_out.get("auth", {})
            auth_out.update({
                "accessToken": updated.access_token,
                "refreshToken": updated.refresh_token,
                "expiresAt": int(updated.expires_at * 1000),
                "refreshExpiresAt": int(updated.refresh_expires_at * 1000),
            })
            payload_out["auth"] = auth_out
            path.write_text(json.dumps(payload_out, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # 写回失败不影响内存中的新 token
    return updated


def valid_credentials() -> Credentials:
    """返回可用凭证；若即将过期则先续期。"""
    cred = load_credentials()
    if cred.is_expired():
        cred = refresh_credentials(cred)
    return cred
