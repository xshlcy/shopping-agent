"""核心：Planner-Executor 多步循环。

和 demo.py 的区别：demo.py 只调一次工具就结束，这里让模型"边做边看"，
可以连续调用多个工具（搜索 -> 看详情 -> 看评价 -> 对比），直到它自己决定结束。

循环结构（这是整个 agent 的心脏）：
    while 未结束 and 未到最大步数:
        1. 把当前对话上下文发给模型，问它"下一步做什么"
        2. 如果模型请求调工具 -> 执行 -> 把结果回传 -> 回到 1
        3. 如果模型直接给文字回答 -> 任务结束，返回
"""
import json
import os
import sys

# 把项目根目录加入 sys.path：无论从哪个目录运行本脚本，都能 import 到 config 和 agent 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI

import config
from agent.tools import TOOLS, execute_tool

client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

SYSTEM_PROMPT = """你是一个跨境电商导购助手，帮助用户从英文商品库（亚马逊真实数据）里挑选商品。严格遵守以下规则：

1. 所有商品信息都必须通过调用工具获取，严禁凭空编造商品名称、价格、评分。
2. 每个推荐都必须来自工具返回的真实数据，并在回答里写明「商品名（英文原样）+ 价格」。
3. 查不到用户要的东西时，如实说明"没找到符合的商品"，绝不编造。
4. 推荐前先调用 get_user_preferences 查看用户偏好（如有）并优先考虑。
5. 涉及"值不值得买"时，先调用 get_reviews 看评价再下结论。
6. 当用户明确表达了购买偏好（场景、预算、品牌、品类喜好）时，调用
   update_user_preferences 把它保存下来，方便下次对话复用。
7. 商品库是英文商品、价格单位为美元(USD)。用户中文需求里的品类/关键词，调用
   search_products 时要翻译成英文（如"蓝牙音箱"→"bluetooth speaker"、"硬盘"→"hard drive"）。
8. 最终回答用中文，条理清晰，每个推荐附美元价格和一句推荐理由。
"""


def run(query: str, verbose: bool = True, memory_file: str = None) -> str:
    """执行一次完整的导购任务，返回最终回答。

    messages 列表就是 agent 的全部状态：system(规则) + user(需求) + 每轮模型输出
    + 每轮工具结果。状态显式放在这里、逐轮累加，而不是散在全局变量里，这就是
    一个 agent 框架和一段"死代码"的分水岭。

    memory_file：指定本次会话使用的独立记忆文件（评估时用于任务隔离），
    None 则用全局默认记忆。用 try/finally 保证结束后恢复，不泄漏到下一次 run。
    """
    token = None
    if memory_file:
        from agent.memory import set_memory_file, reset_memory_file
        token = set_memory_file(memory_file)

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        for step in range(1, config.MAX_STEPS + 1):
            response = client.chat.completions.create(
                model=config.MODEL,
                messages=messages,
                tools=TOOLS,
                temperature=config.TEMPERATURE,
            )
            msg = response.choices[0].message
            messages.append(msg)  # 把模型这轮的输出（可能是文字，也可能是工具调用请求）存起来

            if msg.tool_calls:
                if verbose:
                    names = ", ".join(tc.function.name for tc in msg.tool_calls)
                    print(f"[第 {step} 步] 调用工具: {names}")
                for tc in msg.tool_calls:
                    result = execute_tool(tc)
                    # 关键：把工具结果作为 role="tool" 的消息回传，模型才知道结果
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                continue  # 本轮结束，回到循环开头，让模型基于新结果再决策

            # 模型没有请求工具，说明它认为任务完成，返回最终回答
            return msg.content

        return "（达到最大步数仍未完成，请增大 config.MAX_STEPS 或检查 SYSTEM_PROMPT）"
    finally:
        if token is not None:
            from agent.memory import reset_memory_file
            reset_memory_file(token)


def chat() -> None:
    """交互式多轮对话模式：像聊天一样连续对话，保持上下文和记忆。

    和 run() 的区别：run() 是"一次任务、一个回答"，chat() 是"连续对话"——
    messages 在循环外初始化，每一轮的用户输入和模型回复都累积进去，所以 agent
    记得之前说过的话。长期记忆（memory.json）也会跨轮生效。
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("=" * 50)
    print("导购 agent 已启动，输入你的需求开始对话")
    print("（输入 '退出' / 'quit' 结束）")
    print("=" * 50)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q", "退出"):
            print("再见！")
            break

        messages.append({"role": "user", "content": user_input})

        # 多步工具循环（和 run 一致，但历史保留在 messages 里）
        for step in range(1, config.MAX_STEPS + 1):
            response = client.chat.completions.create(
                model=config.MODEL,
                messages=messages,
                tools=TOOLS,
                temperature=config.TEMPERATURE,
            )
            msg = response.choices[0].message
            messages.append(msg)

            if msg.tool_calls:
                names = ", ".join(tc.function.name for tc in msg.tool_calls)
                print(f"  [调用工具: {names}]")
                for tc in msg.tool_calls:
                    result = execute_tool(tc)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                continue  # 工具结果回传后，继续循环让模型再决策

            # 模型没有请求工具，输出最终回答，回到输入循环等下一轮
            print(f"\n助手: {msg.content}")
            break


if __name__ == "__main__":
    import sys
    try:
            chat()
    except Exception as e:
        print("运行出错，常见原因见 docs/GUIDE.md")
        print("原始错误：", e)
