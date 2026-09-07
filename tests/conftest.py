"""pytest 启动准备：把 AstrBot 根加进 sys.path，使 data.plugins.* 包链可导入。

测试导入约定（plugin-import-model 规范）：一律用
data.plugins.astrbot_plugin_feather_art.xxx 全路径，与框架运行时的包结构一致；
不 import main.py（它的装饰器依赖框架上下文），只测无框架依赖的模块：
feather_art（算法包）/ service / deliver（组件仅构造，不发送）/ hardening /
limiter / config。
"""

import sys
from pathlib import Path


def _find_astrbot_root() -> Path:
    """向上找包含 astrbot 包的目录（开发目录或运行目录都适用）。"""
    cursor = Path(__file__).resolve().parent.parent
    for _ in range(6):
        if (cursor / "astrbot").is_dir():
            return cursor
        cursor = cursor.parent
    raise RuntimeError("未找到 AstrBot 根目录（含 astrbot 包）。")


_ASTRBOT_ROOT = _find_astrbot_root()
if str(_ASTRBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASTRBOT_ROOT))

# 测试辅助模块以顶层名导入（避免与 AstrBot 根目录的 tests 包同名冲突）
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
