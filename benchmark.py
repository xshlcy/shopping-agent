"""性能对比：C++ 倒排索引 vs Python 线性扫描。

用法：python benchmark.py

生成 N 条模拟商品，对比同一种搜索需求下两种实现的查询耗时：
  - C++ 倒排索引（tag 精确 O(1) + name 子串 unigram 缩小候选）
  - Python 线性扫描（朴素 `keyword in name or keyword in tag`）

这是 M3 C++ 模块的量化证据——"为什么用 C++"用数字说话，而不是空口。
"""
import random
import sys
import time

sys.path.insert(0, ".")

from agent import fast_index

N = 100000  # 模拟商品数

CATEGORIES = ["降噪耳机", "蓝牙耳机", "智能音箱", "高速吹风机", "电动牙刷",
              "机械键盘", "4K显示器", "旗舰手机", "充电宝", "护眼台灯"]
ATTRIBUTES = ["降噪", "蓝牙", "无线", "便携", "智能", "高速", "护眼", "大容量", "旗舰", "入门"]

random.seed(42)

print(f"生成 {N} 条模拟商品数据...")
names = []
prices = []
tags = []
for i in range(N):
    cat = CATEGORIES[i % len(CATEGORIES)]
    names.append(f"品牌{i % 100} {cat} 型号{i}")
    prices.append(random.uniform(50, 5000))
    tags.append([cat, ATTRIBUTES[i % len(ATTRIBUTES)], ATTRIBUTES[(i + 3) % len(ATTRIBUTES)]])

# 建 C++ 索引（计时）
t0 = time.perf_counter()
idx = fast_index.ProductIndex()
idx.build(names, prices, tags)
build_time = time.perf_counter() - t0
print(f"C++ 索引构建耗时: {build_time:.3f}s（一次性，之后每次查询都受益）\n")


def python_search(keyword, max_price):
    """朴素 Python 实现：线性扫描所有商品。"""
    return [i for i in range(N)
            if (keyword in names[i] or any(keyword in t for t in tags[i]))
            and prices[i] <= max_price]


INF = float("inf")
REPS = 50

print(f"{'关键词':<8} {'C++(微秒)':>10} {'Python(微秒)':>13} {'加速比':>8}")
print("-" * 44)

for kw in ["降噪", "耳机", "音箱", "吹风机", "充电宝", "机械键盘", "苹果"]:
    t0 = time.perf_counter()
    for _ in range(REPS):
        idx.search(kw, INF)
    cpp_us = (time.perf_counter() - t0) / REPS * 1e6

    t0 = time.perf_counter()
    for _ in range(REPS):
        python_search(kw, INF)
    py_us = (time.perf_counter() - t0) / REPS * 1e6

    speedup = py_us / cpp_us if cpp_us > 0 else float("inf")
    print(f"{kw:<8} {cpp_us:>9.1f} {py_us:>12.1f} {speedup:>7.0f}x")

print("-" * 44)
print("注：C++ 是 tag 精确匹配 + name 子串(unigram候选)，Python 是纯线性扫描。")
print("    数据量越大，倒排索引优势越明显（Python 是 O(n)，C++ 查询不随 n 线性增长）。")
