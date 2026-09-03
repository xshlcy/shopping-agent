"""全局配置：API key、模型、循环步数等。

安全说明：API key 绝不硬编码进代码，而是从环境变量 `DEEPSEEK_API_KEY` 或
项目根目录的 `.env` 文件读取。`.env` 已被 .gitignore 排除，不会提交到 GitHub。
首次使用请复制 `.env.example` 为 `.env` 并填入你自己的 key。
"""
import os


# ---- 加载 .env 文件（简单手写解析，避免引入额外依赖）----
def _load_env() -> None:
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

# ===== DeepSeek API（OpenAI 兼容接口）=====
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# ===== Agent 行为 =====
MAX_STEPS = 6       # Planner-Executor 循环最多走几步（防止死循环烧钱）
TEMPERATURE = 0.1   # 低温度 = 输出更稳定，工具调用不容易跑偏

# ===== 数据文件路径（用 __file__ 算绝对路径，保证从任意目录运行都能找到）=====
_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE, "data")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.json")
MEMORY_FILE = os.path.join(DATA_DIR, "memory.json")
