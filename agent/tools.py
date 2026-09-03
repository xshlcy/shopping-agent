"""工具层：定义 agent 能用的工具 + 实现 + 分发器。

一个"工具"在代码里是两件事，务必分清：
  1. schema —— 放在 TOOLS 里，是给模型看的"说明书"（工具名、用途、参数）
  2. 实现 —— 放在下面的函数里，是真正执行的逻辑
  execute_tool 负责把模型请求的"工具名"映射到真实函数，这是解耦的关键。
"""
import json

from config import PRODUCTS_FILE
from agent.memory import get_preferences, update_preferences

# 模块导入时一次性加载商品数据
with open(PRODUCTS_FILE, encoding="utf-8") as f:
    PRODUCTS = json.load(f)


# ---------- C++ 倒排索引（可选加速）----------
# 尝试加载 C++ 编译的倒排索引；加载失败（比如没编译 .pyd）则回退纯 Python 线性扫描。
# 这样项目既能享受 C++ 加速，又不会因为缺 .pyd 而跑不起来。
try:
    from agent import fast_index
    _INDEX = fast_index.ProductIndex()
    _INDEX.build(
        [p["name"] for p in PRODUCTS],
        [float(p["price"]) for p in PRODUCTS],
        [p["tags"] for p in PRODUCTS],
    )
    _HAS_CPP_INDEX = True
except ImportError:
    _INDEX = None
    _HAS_CPP_INDEX = False


# ---------- 工具 schema（给模型看的说明书） ----------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "按关键词和可选价格上限搜索商品，返回匹配商品列表（含 id、名称、价格、评分）",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如 '降噪耳机' 或 '头戴'"},
                    "max_price": {"type": "number", "description": "价格上限（元），不填则不限价"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_detail",
            "description": "根据商品 id 查看单个商品的完整信息（参数、评分、评价数）",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "商品的数字 id"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reviews",
            "description": "根据商品 id 查看用户评价摘要，用于判断值不值得买",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "商品的数字 id"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_preferences",
            "description": "获取记忆里保存的用户偏好（如购买场景、预算），用于个性化推荐",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_preferences",
            "description": "保存一条用户偏好到长期记忆，供下次对话使用。当用户明确表达了购买场景、预算、品牌喜好等时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "偏好名，如 max_budget（预算）、scenario（场景）、brand（品牌）"},
                    "value": {"type": "string", "description": "偏好的值，如 '500' 或 '给父母买'"},
                },
                "required": ["key", "value"],
            },
        },
    },
]


# ---------- 工具的真实实现 ----------
def _summarize(p: dict) -> dict:
    """把商品精简成给模型看的摘要（省 token）。"""
    return {
        "id": p["id"],
        "name": p["name"],
        "price": p["price"],
        "rating": p["rating"],
        "tags": p["tags"],
    }


def search_products(keyword: str, max_price=None):
    """关键词 + 价格过滤。优先用 C++ 倒排索引，失败则回退 Python 线性扫描。

    注：C++ 索引对 tag 是精确匹配、对 name 是子串匹配；对常见查询（完整 tag
    或 name 里的词）与 Python 线性扫描结果一致。
    """
    limit = float("inf") if max_price is None else float(max_price)

    if _HAS_CPP_INDEX:
        # C++ 索引返回的是 PRODUCTS 列表的下标
        ids = _INDEX.search(keyword, limit)
        results = [_summarize(PRODUCTS[i]) for i in ids]
    else:
        results = [
            _summarize(p)
            for p in PRODUCTS
            if (keyword in p["name"] or any(keyword in t for t in p["tags"]))
            and p["price"] <= limit
        ]
    return {"count": len(results), "products": results}


def get_product_detail(product_id: int):
    """返回单个商品完整信息。"""
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    return {"error": f"未找到 id 为 {product_id} 的商品"}


def get_reviews(product_id: int):
    """返回评价摘要。"""
    for p in PRODUCTS:
        if p["id"] == product_id:
            return {
                "name": p["name"],
                "rating": p["rating"],
                "reviews_count": p["reviews"],
                # 用 .get() 而不是 p["review_summary"]：真实数据常缺字段，
                # 直接下标访问会 KeyError 崩溃（data 里 id=28 就故意缺这个字段）
                "summary": p.get("review_summary", "暂无评价"),
            }
    return {"error": f"未找到 id 为 {product_id} 的商品"}


def get_user_preferences():
    """读记忆里的用户偏好。"""
    prefs = get_preferences()
    return prefs if prefs else {"提示": "暂无保存的偏好"}


def update_user_preferences(key: str, value: str):
    """把一条用户偏好写进长期记忆，返回更新后的全部偏好。"""
    prefs = update_preferences(key, value)
    return {"已保存偏好": prefs}


# ---------- 工具分发器：模型请求的工具名 -> 真实函数 ----------
_TOOL_FUNCS = {
    "search_products": search_products,
    "get_product_detail": get_product_detail,
    "get_reviews": get_reviews,
    "get_user_preferences": get_user_preferences,
    "update_user_preferences": update_user_preferences,
}


def execute_tool(tool_call):
    """执行一次工具调用，返回结果（会由 agent 序列化后回传给模型）。"""
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)  # arguments 是 JSON 字符串
    except json.JSONDecodeError:
        return {"error": f"工具参数不是合法 JSON: {tool_call.function.arguments}"}

    func = _TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"未知工具: {name}"}

    try:
        return func(**args)
    except TypeError as e:
        # 模型偶尔会传错参数（缺参/多参），这里接住并返回可读错误，而不是让程序崩溃
        return {"error": f"工具 {name} 参数错误: {e}"}
