# 电商导购 Agent（简历项目 · M3 版）

一个能**多步调用工具**、**记住用户偏好**、且用 **C++ 倒排索引加速搜索**的电商导购 agent：用户一句话 → agent 自己决定搜索、查详情、看评价、读/写偏好 → 给出带价格的推荐。目标是拼多多 AI agent 实习，方向为「agent 应用/框架」，C++ 是差异化亮点。

## 项目结构

```
shopping-agent/
├── demo.py            # 入门：单次工具调用的最小示例（先看这个）
├── config.py          # 配置：API key、模型、循环步数
├── benchmark.py       # 性能对比：C++ 倒排索引 vs Python 线性扫描
├── requirements.txt
├── cpp/
│   └── index.cpp      # C++ 倒排索引源码（pybind11），加速 search_products
├── data/
│   ├── products.json  # 30 条商品数据，跨品类，故意含脏数据（缺字段）
│   └── memory.json    # 用户偏好（长期记忆，agent 可读写）
├── agent/
│   ├── tools.py       # 5 个工具 + 脏数据防御 + C++ 索引集成（失败回退 Python）
│   ├── agent.py       # 核心：Planner-Executor 多步循环 + memory 隔离
│   ├── memory.py      # 记忆层：contextvars 会话级隔离
│   └── fast_index.pyd # C++ 编译产物（可选，缺失时自动回退纯 Python）
├── eval/
│   ├── tasks.py       # 评估任务集：30 条需求，分 5 类
│   └── eval.py        # 评估：成功率 + 质量分（LLM-judge + 硬规则，任务隔离）
└── docs/
    ├── GUIDE.md       # ⭐ 问题 / 解决方法 / 知识点
    └── INTERVIEW.md   # ⭐ 面试复盘：踩坑 + 设计决策 + 高频问答
```

## 快速开始

```bash
# 1. 装依赖（用 python -m pip + 清华镜像）
python -m pip install openai pybind11 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 申请 API key：https://platform.deepseek.com
#    填到 config.py 的 API_KEY

# 3. （可选）编译 C++ 加速模块（需要 g++，缺了也能跑，会自动回退 Python）
cd cpp
g++ -O3 -shared -std=c++17 index.cpp -o ../agent/fast_index.pyd \
  $(python -m pybind11 --includes) \
  "$(python -c "import sys; print(sys.base_prefix + '\\python310.dll')")" \
  -static-libgcc -static-libstdc++ -static
cd ..

# 4. 运行 agent（默认交互式多轮对话，输入"退出"结束；加 --demo 跑单次演示）
python agent/agent.py

# 5. 跑评估（30 个任务，成功率 + 质量分）
python eval/eval.py

# 6. 性能对比（C++ vs Python，量化加速比）
python benchmark.py
```

## C++ 加速效果（benchmark 实测，10 万条商品）

| 指标 | 数值 |
|---|---|
| 常规查询加速比 | **19–42 倍** |
| 索引构建耗时 | 0.27 秒（一次性） |

`search_products` 从 Python O(n) 线性扫描 → C++ 倒排索引（tag 精确 O(1) + name 子串 unigram 缩小候选）。数据量越大优势越明显。

## 建议学习顺序

1. 先读 `demo.py`，理解 function calling 的「模型请求 → 执行 → 回传」三步
2. 再读 `agent/agent.py`，理解「循环」怎么把一次调用变成多步任务
3. 读 `agent/tools.py`，理解工具设计 + 脏数据防御 + C++ 索引集成
4. 读 `cpp/index.cpp`，理解倒排索引 + pybind11 绑定
5. 最后读 `eval/`，理解「成功率」和「质量分」+ 评估隔离

## 文档

- **[docs/GUIDE.md](docs/GUIDE.md)** —— 运行报错、踩坑、知识点
- **[docs/INTERVIEW.md](docs/INTERVIEW.md)** —— 面试复盘：踩坑 + 设计决策 + 高频问答（含 docx 版）
