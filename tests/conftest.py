"""测试全局配置。

让 pytest 在「未安装包」时也能直接找到 src/wbapi；
在 CI 中通过 pip install -e . 安装时，这条路径同样无害。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
