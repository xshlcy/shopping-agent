"""记忆层（M2 版）：支持会话隔离的长期记忆。

真正的 agent 记忆分"短期(会话内)"和"长期(跨会话)"。这里长期记忆用 JSON 文件。

关键改进：用 contextvars 管理「当前会话的记忆文件路径」。默认指向全局
MEMORY_FILE，但一次 run() 可以切到独立文件——这样评估时每个任务用各自
的记忆，互不污染（这是"评估无状态"的基础）。

contextvars 比全局变量好的地方：它是"上下文局部"的，正确支持嵌套和并发，
不会像全局变量那样在不同会话间串味。
"""
import contextvars
import json
import os

from config import MEMORY_FILE

# 当前上下文的记忆文件路径，默认全局 MEMORY_FILE
_current_memory_file = contextvars.ContextVar("memory_file", default=MEMORY_FILE)


def set_memory_file(path: str):
    """切换当前上下文要用的记忆文件，返回 token（用于之后恢复）。"""
    return _current_memory_file.set(path)


def reset_memory_file(token) -> None:
    """把记忆文件恢复到 set 之前的值。"""
    _current_memory_file.reset(token)


def _memory_file() -> str:
    """取当前上下文应使用的记忆文件路径。"""
    return _current_memory_file.get()


def get_preferences() -> dict:
    """读用户偏好，文件不存在或为空时返回空 dict。"""
    path = _memory_file()
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("preferences", {})


def update_preferences(key: str, value) -> dict:
    """更新某个偏好项并写回文件，返回更新后的全部偏好。"""
    path = _memory_file()
    data = {"preferences": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("preferences", {})[key] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data["preferences"]
