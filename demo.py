"""
导购 Agent 最小演示 —— M1 第 1 周的地基

目标链路：
    用户一句话 -> 模型决定调用 search_products -> 我们执行工具
              -> 把结果回传给模型 -> 模型基于结果生成回答

运行前准备：
    1. pip install openai
    2. 到 https://platform.deepseek.com 申请一个 API key，填到下面 API_KEY
    3. python demo.py
"""

import json
import os
from openai import OpenAI

# ============ 0. 配置 ============
# 从环境变量或项目根目录的 .env 读 key（不硬编码，避免泄露到 GitHub）
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ============ 1. 模拟商品库（先 mock，第 2 周再接真实数据） ============
PRODUCTS = [
    {"id": 1, "name": "索尼 WH-1000XM4 无线降噪耳机", "price": 1899, "tags": ["降噪", "头戴", "耳机"], "rating": 4.8, "reviews": 12000},
    {"id": 2, "name": "漫步者 W820NB 降噪耳机", "price": 399, "tags": ["降噪", "头戴", "耳机"], "rating": 4.5, "reviews": 30000},
    {"id": 3, "name": "小米 Redmi Buds 4 Pro 降噪耳机", "price": 299, "tags": ["降噪", "入耳", "耳机"], "rating": 4.4, "reviews": 8000},
    {"id": 4, "name": "Apple AirPods Pro 2 主动降噪耳机", "price": 1899, "tags": ["降噪", "入耳", "耳机"], "rating": 4.9, "reviews": 50000},
    {"id": 5, "name": "Bose QuietComfort 45 降噪耳机", "price": 1599, "tags": ["降噪", "头戴", "耳机"], "rating": 4.7, "reviews": 9000},
    {"id": 6, "name": "华为 FreeBuds Pro 3 降噪耳机", "price": 1199, "tags": ["降噪", "入耳", "耳机"], "rating": 4.6, "reviews": 15000},
]

# ============ 2. 工具定义（告诉模型"你能做什么"） ============
# 这段 schema 只是"说明书"，描述工具的名字、用途、参数。
# 模型读它，然后决定"这个任务该不该调用这个工具、参数填什么"。
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "按关键词搜索商品，可选价格上限，返回匹配的商品列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如 '降噪耳机'"},
                    "max_price": {"type": "number", "description": "价格上限（元），不填则不限价"},
                },
                "required": ["keyword"],  # keyword 必填，max_price 可选
            },
        },
    }
]


# ============ 3. 工具的真实实现 ============
def search_products(keyword: str, max_price=None):
    """在 mock 商品库里做关键词 + 价格过滤。"""
    results = []
    for p in PRODUCTS:
        # 命中条件：名字里含关键词，或标签里含关键词
        hit = keyword in p["name"] or any(keyword in t for t in p["tags"])
        if hit and (max_price is None or p["price"] <= max_price):
            results.append(p)
    return results  # 返回列表，模型能读懂（后面会序列化成 JSON 回传）


# ============ 4. 工具分发器（把模型请求的工具名映射到真实函数） ============
# 第 2 周加多工具时，这里会扩展成 if/elif 或字典映射。
def execute_tool(tool_call):
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)  # arguments 是 JSON 字符串，要解析
    if name == "search_products":
        return search_products(**args)
    return {"error": f"未知工具: {name}"}


# ============ 5. 主流程：一轮对话 + 工具调用 + 回传 ============
def run(user_query: str) -> str:
    # messages 就是"对话上下文"，agent 的状态从一开始就显式放在这里
    messages = [{"role": "user", "content": user_query}]

    # 第一轮：问模型"你要不要调用工具？"
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
    )
    msg = response.choices[0].message
    messages.append(msg)  # 把模型的回复（含工具调用请求）也放进上下文

    # 如果模型请求了工具调用
    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            result = execute_tool(tool_call)
            # 关键一步：把工具执行结果作为一条 "tool" 消息回传给模型
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,   # 必须对应，模型才知道结果属于哪个调用
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        # 第二轮：模型拿到工具结果，生成最终回答（这次不用传 tools，直接答）
        response2 = client.chat.completions.create(
            model=MODEL,
            messages=messages,
        )
        return response2.choices[0].message.content

    # 模型没调工具（比如只是闲聊），直接返回它的回答
    return msg.content


# ============ 6. 演示 ============
if __name__ == "__main__":
    try:
        answer = run("帮我找最贵的耳机")
        print("===== Agent 回答 =====\n")
        print(answer)
    except Exception as e:
        print("出错了，常见原因：")
        print("  - API key 没填对（去 platform.deepseek.com 申请）")
        print("  - 没装 openai 库（pip install openai）")
        print("  - 网络问题 / 余额不足")
        print("\n原始错误：", e)
