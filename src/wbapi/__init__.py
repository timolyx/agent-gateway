"""agent-gateway —— 把 WorkBuddy / CodeBuddy 订阅模型暴露为本地 OpenAI 兼容 API。

设计原则
--------
1. 不预置、不分发、不硬编码任何账号凭证。
2. 登录走官方 ``codebuddy-agent-sdk`` 的浏览器 OAuth，token 保存在用户自己的机器。
3. 本包只读取本机已有的登录态，并用它调用官方云端端点。
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
