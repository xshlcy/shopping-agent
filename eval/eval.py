"""评估体系 v3：30 条任务，成功率 + 质量分，且修复了两个评估自身的缺陷。

相比 v2 的改进（都是"评估本身也要被评估"的体现）：
  1. **memory 隔离**：每个任务用独立的临时记忆文件，消除任务间状态泄漏。
  2. **预算合规纳入 judge**：llm_judge 增加「预算合规」维度（它懂"左右/以下/替代"的
     语义），check_budget 正则退居为"辅助启发式"，只抓最明显的确定性超支。

指标：
  - 成功率（0/1）：任务是否被正确「处理」（含"如实说找不到"这种正确失败）
  - 质量分（1-5）：需求满足 / 证据充分 / 无幻觉 / 预算合规 四个维度平均
"""
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict

# 把项目根目录加入 sys.path，保证能 import 到 config / agent / eval
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI

import config
from agent.agent import run
# 导入任务集：优先用「包导入」（`python -m eval.eval` / 被 import 时 eval 是包）；
# 若失败则回退「同目录导入」（`python eval.py` 直接运行时，脚本名 eval.py 会和包名
# eval 冲突，此时 eval 不是包，只能同目录 import）。
try:
    from eval.tasks import TASKS
except ModuleNotFoundError:
    from tasks import TASKS

judge_client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

# 每任务跑几遍取平均（>1 能减少 LLM-judge 随机性，但更费 token，默认 1）
RUNS = 1


def llm_judge(query: str, answer: str, category: str) -> dict:
    """让另一个模型当评委，输出结构化评分（四个质量维度 + 完成与否）。"""
    prompt = (
        "你是一个严格的导购 agent 评估员。根据用户需求和回答，输出 JSON 评分：\n\n"
        f"任务类型：{category}\n"
        f"用户需求：{query}\n\n"
        f"agent 回答：\n{answer}\n\n"
        "评分规则：\n"
        "- 完成(bool)：agent 是否正确处理了需求。注意「边界负例」类任务里，"
        "正确行为是如实说明找不到/没有符合的商品，这也算完成（true）；编造商品则算未完成(false)。\n"
        "- 需求满足(int,1-5)：是否真正解决了用户需求\n"
        "- 证据充分(int,1-5)：推荐是否基于真实信息、是否写明价格\n"
        "- 无幻觉(int,1-5)：是否编造了不存在的商品或价格\n"
        "- 预算合规(int,1-5)：推荐是否在用户预算内。注意「100元左右→129元」「没有20元的、"
        "最便宜269元」这类是合理或诚实回答，不该扣分；只有明确推荐了超预算商品才扣分。\n\n"
        '只输出 JSON，格式：{"完成": true, "需求满足": 4, "证据充分": 5, "无幻觉": 5, "预算合规": 5}'
    )
    resp = judge_client.chat.completions.create(
        model=config.MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    try:
        data = json.loads(resp.choices[0].message.content)
        # 容错：模型偶尔返回字符串 "true" 而不是布尔
        if isinstance(data.get("完成"), str):
            data["完成"] = data["完成"].lower() == "true"
        return data
    except (json.JSONDecodeError, AttributeError):
        return {"完成": False, "需求满足": 0, "证据充分": 0, "无幻觉": 0, "预算合规": 0}


def check_budget(query: str, answer: str) -> bool:
    """硬规则（辅助启发式）：检查明确推荐是否超预算。

    正则没有语义，所以这里只做"减误报"处理——诚实拒绝（找不到/没有）不算超支。
    它的定位是辅助：主力判断交给 llm_judge 的「预算合规」字段，这里只抓最明显的
    确定性超支，宁可漏报不可误报。
    """
    m = re.search(r"(\d+)\s*元", query)
    if not m:
        return True  # 需求没提预算，跳过
    budget = int(m.group(1))

    # 诚实拒绝（正确失败）不算超支——这是 v3 的关键修复
    if any(w in answer for w in ["找不到", "没有", "抱歉", "无法", "未找到", "不存在", "不推荐"]):
        return True

    prices = [int(x) for x in re.findall(r"(\d+)\s*元", answer)]
    if not prices:
        return True
    return all(p <= budget for p in prices)


def main():
    print("=" * 66)
    print(f"评估开始：共 {len(TASKS)} 个任务，每任务跑 {RUNS} 轮")
    print("=" * 66)

    # 每个任务用独立记忆文件，消除状态泄漏；用完整个临时目录一起清掉
    tmpdir = tempfile.mkdtemp(prefix="eval_memory_")

    stat = defaultdict(lambda: {"完成": 0, "总分": 0.0, "计数": 0})
    budget_fail = 0
    total_done = 0

    try:
        for i, task in enumerate(TASKS, 1):
            query, category = task["query"], task["category"]
            print(f"\n[{i}/{len(TASKS)}] ({category}) {query}")

            # 每任务独立的记忆文件（初始不存在 = 空偏好），任务间互不影响
            memory_file = os.path.join(tmpdir, f"task_{i}.json")

            scores_list = []
            for r in range(RUNS):
                answer = run(query, verbose=False, memory_file=memory_file)
                scores = llm_judge(query, answer, category)
                scores_list.append(scores)
                if not check_budget(query, answer):
                    budget_fail += 1

            done = any(s.get("完成", False) for s in scores_list)
            total_done += done

            # 质量分：四个维度的平均（需求满足/证据充分/无幻觉/预算合规）
            avg = sum(
                (s.get("需求满足", 0) + s.get("证据充分", 0)
                 + s.get("无幻觉", 0) + s.get("预算合规", 0)) / 4
                for s in scores_list
            ) / RUNS

            stat[category]["完成"] += 1 if done else 0
            stat[category]["总分"] += avg
            stat[category]["计数"] += 1

            print(f"    {'✓ 完成' if done else '✗ 未完成'}  质量分 {avg:.1f}/5")

        # ---- 汇总输出 ----
        print("\n" + "=" * 66)
        print("【总体】")
        print(f"  成功率：{total_done}/{len(TASKS)} = {total_done / len(TASKS) * 100:.1f}%")
        overall_q = sum(s["总分"] for s in stat.values()) / len(TASKS)
        print(f"  平均质量分：{overall_q:.2f}/5")
        print(f"  预算超支(硬规则启发式)：{budget_fail} 次  " +
              ("⚠ 需人工复核" if budget_fail else "✅ 无"))

        print("\n【分类明细】")
        for cat in ["搜索推荐", "对比", "评价", "偏好记忆", "边界负例"]:
            s = stat[cat]
            n = s["计数"]
            rate = s["完成"] / n * 100 if n else 0
            q = s["总分"] / n if n else 0
            print(f"  {cat:<6} 成功率 {s['完成']}/{n} ({rate:.0f}%)  质量分 {q:.2f}/5")

        print("=" * 66)
        print("提示：看分类明细里哪类最弱，就去针对性改 SYSTEM_PROMPT 或工具。")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)  # 清理临时记忆文件


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("运行出错，常见原因见 docs/GUIDE.md")
        print("原始错误：", e)
