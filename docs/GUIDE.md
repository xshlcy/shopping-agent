# 项目指南：问题 / 解决方法 / 知识点

这份文档是你半年的「随行手册」。分三部分：

1. **核心概念** —— 每个知识点，面试会问
2. **运行报错与解决方法** —— 踩坑对照表
3. **下一步路线** —— M1 → M2 → M3 该怎么走

---

## 一、核心概念（面试会问的知识点）

### 1. 什么是 function calling（工具调用）？

大模型只能"生成文字"，本身不能搜商品、查数据库。function calling 就是给模型一套「工具说明书」，让模型：

- **不直接执行**工具，而是输出一个"我想调用 `search_products`，参数是 `{"keyword": "降噪耳机"}`"的**结构化请求**；
- 你的代码收到请求 → 真正执行函数 → 把结果作为 `role="tool"` 消息回传；
- 模型再基于结果生成文字。

一句话：**模型负责"决定做什么"，你的代码负责"真的去做"，结果再喂回模型。** 模型从来没有自主执行过任何代码——这是理解 agent 安全性和可控性的基础。

### 2. Agent 循环（Planner-Executor）

`demo.py` 是"一次调用"，`agent/agent.py` 是"循环"——这个循环就是 agent 和普通聊天机器人的区别：

```
while 未结束 and 未到最大步数:
    模型看上下文 → 决定下一步
    ├─ 要调工具 → 执行 → 结果回传 → 再来一轮
    └─ 直接回答 → 结束
```

三个关键设计点：

- **`MAX_STEPS` 上限**：防止模型陷入"反复调工具却给不出结果"的死循环，把 token 烧光。这是生产 agent 的必备保险。
- **状态显式化**：agent 的全部状态就是一个 `messages` 列表（system + user + 每轮模型输出 + 每轮工具结果），逐轮累加。状态藏进全局变量 = 无法测试、无法并发、无法恢复。
- **`temperature` 低**：工具调用需要稳定，温度高模型容易"跑偏"（把参数写错、重复调用）。

### 3. 工具怎么设计（这是 agent 工程的核心判断）

`tools.py` 里每个工具都遵循一个原则：**原子、可组合、返回精简**。

- **原子**：`search_products` 只干搜索，`get_reviews` 只看评价。不要做一个"大而全的 `do_everything`"。拆细了模型更容易选对、出错更容易定位、也更好评估。
- **返回精简**：`search_products` 只返回 id/name/price/rating/tags，不把 `specs`、`review_summary` 全塞进去——那是 `get_product_detail` 的活。**每个 token 都是钱**，把用不到的字段喂给模型就是在烧钱。
- **工具即边界**：模型能做的，不超出你给的工具集合。这就是为什么"工具设计 = 能力边界设计"。

### 4. 事实核查 / 防幻觉（业界最关心的点）

导购 agent 最大的风险是**推荐了不存在的商品、编造价格**。这个项目用了两层防护：

- **提示词约束**（软）：`SYSTEM_PROMPT` 要求"必须来自工具数据、查不到就明说"。
- **硬规则**（硬）：`eval.py` 的 `check_budget` 会检查回答里的价格是否超预算；更进一步的版本是检查回答里每个"商品名+价格"能否在商品库里找到对应。

面试时能讲清楚"软约束不够，必须有硬校验"，是很大的加分项。

### 5. 记忆分层

- **短期记忆** = 对话上下文（`messages` 列表），会话结束就没了。
- **长期记忆** = `data/memory.json`，跨会话保存用户偏好。

真实系统里长期记忆要用向量数据库 + 结构化偏好图谱，这里是 M1 的最简实现，先建立概念。

M2 加了 `contextvars` **会话级隔离**——一次 `run()` 可以切到独立的记忆文件（`run(memory_file=...)`），结束后自动恢复。这是「评估无状态」的基础：评估时每个任务用独立临时记忆，互不污染。

### 6. 为什么第一天就要评估

没有指标的 agent 只是"看着能跑"。评估给你两个东西：

- **回归能力**：改了提示词/工具后，跑一遍评估就知道"变好了还是变坏了"。
- **面试数字**："工具调用成功率 92%、预算合规率 95%"比"实现了导购 agent"有力十倍。

评估的两个通道：**LLM-judge**（软，衡量"回答合不合理"）和**硬规则**（硬，抓确定性错误如超预算）。

### 7. 脏数据防御（真实世界 vs 理想数据）

M1 的数据是规整的；真实电商数据一定不规整——缺字段、价格是范围字符串、重复条目。

M3 换成了真实 Amazon 数据集（234 条），并保留了 4 条数据集里**天然**缺字段的商品（2 条缺 `specs`、2 条缺 `review_summary`）。如果工具用下标 `p["review_summary"]` 访问，遇到缺字段会直接 `KeyError` 崩溃，整个 agent 挂掉。所以工具层要用 `.get("review_summary", "暂无评价")` 防御。

**面试点**：能说出"真实数据是脏的，工具层必须防御性解析" = 有生产经验的味道。

### 8. 成功率 vs 质量分（两个维度别混成一个总分）

一个 agent 可能"每次都回应"但质量差，也可能"经常拒绝"但一旦做就做得好。混成一个总分这两个信息就丢了：

- **成功率**（0/1）：任务是否被正确**处理**——注意「边界负例」里"如实说找不到"也算成功（正确失败），编造才算失败。
- **质量分**（1-5）：处理得好不好（需求满足 / 证据充分 / 无幻觉）。

### 9. 评估的可信度：隔离 + eval the eval

评估数字要可信，得满足两条：

- **无状态（隔离）**：任务之间不能互相影响。M2 修复了一个真 bug——评估时「偏好记忆」任务把偏好写进共享 `memory.json`，污染了后续任务。用 `contextvars` 会话级隔离 + 每任务独立临时文件后，任务间零泄漏。
- **评估本身也要被评估（eval the eval）**：硬规则正则没语义，会把「预算重述」「替代品价格」误判成「超支」，修复后误报从 5 降到 0。所以评估要「双通道」——硬规则兜确定性错误（宁可漏报不可误报），LLM-judge 兜语义（加「预算合规」维度）。

面试官问"你的评估可信吗"，这两条就是答案。

### 10. C++ 倒排索引（性能关键路径）

`search_products` 原本是 Python O(n) 线性扫描。用 C++ + pybind11 做了倒排索引：

- tag 精确匹配走哈希倒排 O(1)
- name 子串匹配用 unigram（单字符）倒排缩小候选集，再精确 `find` 验证

实测（10 万条商品）查询加速 19–42 倍，索引构建 0.27 秒。数据量越大优势越明显（Python 是 O(n)，C++ 查询不随 n 线性增长）。

**面试点**：agent 的性能关键路径不在应用层而在底层——工具执行、推理引擎、约束解码。C++ 背景在这里是差异化优势，不是短板。

---

## 二、运行报错与解决方法（对照表）

### 报错 1：`openai.APIConnectionError` / `Connection error`

- **原因**：连不上 `https://api.deepseek.com`。可能是网络、代理、或公司/校园网限制。
- **解决**：确认能访问 DeepSeek；若用代理，设置 `HTTPS_PROXY` 环境变量；或在 `config.py` 换成通义千问等其它 OpenAI 兼容服务的 `BASE_URL`（千问：`https://dashscope.aliyuncs.com/compatible-mode/v1`）。

### 报错 2：`openai.AuthenticationError` / 401

- **原因**：API key 填错、失效、或额度用尽。
- **解决**：去 platform.deepseek.com 重新生成 key；确认 `config.py` 里的 key 没有多余空格；充值余额。

### 报错 3：`openai.NotFoundError` 或 `model not found`

- **原因**：模型名写错，或该服务商没有这个模型。
- **解决**：确认 `config.MODEL`。DeepSeek 用 `deepseek-chat`；换服务商要同步换 `BASE_URL` 和 `MODEL`（千问用 `qwen-plus` 等）。

### 报错 4：`openai.RateLimitError` / 429

- **原因**：请求太频繁，触发了服务商限流。
- **解决**：加 `time.sleep` 重试；或在循环里加退避（后面 M2 会做）。

### 报错 5：`ModuleNotFoundError: No module named 'openai'`

- **原因**：没装依赖，或装在了错误的 Python 环境。
- **解决**：`pip install openai`；确认用的是同一个 Python（`python -c "import openai; print(openai.__version__)"`）。

### 报错 6：`ModuleNotFoundError: No module named 'config'` / `'agent'`

- **原因**：运行时的工作目录不对。`eval/eval.py` 已经内置了路径处理，但 `python agent/agent.py` 必须从**项目根目录**运行。
- **解决**：始终在 `shopping-agent/` 目录下运行：`python agent/agent.py`。

### 报错 7：中文乱码 / `UnicodeDecodeError`

- **原因**：文件或终端编码不对（Windows 常见）。
- **解决**：数据文件已用 UTF-8 读写；若终端输出乱码，在命令行先执行 `chcp 65001`，或用 `PYTHONIOENCODING=utf-8 python agent/agent.py`。

### 报错 8：模型不调用工具，直接空谈

- **现象**：模型直接回复"根据我的了解……"，没走工具。
- **原因**：`SYSTEM_PROMPT` 约束不够强，或 `tools` 参数没正确传入。
- **解决**：确认 `agent.py` 的 `create()` 里传了 `tools=TOOLS`；强化 `SYSTEM_PROMPT`，加一句"回答前必须先调用工具获取真实数据"。

### 报错 9：模型反复调用同一个工具 / 死循环

- **现象**：一直调 `search_products`，永远不结束。
- **原因**：提示词没要求"基于结果给出最终结论"，或结果里缺它要找的信息。
- **解决**：`MAX_STEPS` 已经在兜底；同时在 `SYSTEM_PROMPT` 里明确"信息足够后就停止调用工具，直接给出推荐"。

### 报错 10：工具参数 JSON 解析失败 / 参数错误

- **现象**：`execute_tool` 报参数错误。
- **原因**：模型偶尔生成不合法的参数。
- **解决**：`execute_tool` 已经做了 `try/except` 兜底，会返回可读错误让模型自己纠正。这是 agent 健壮性的体现——**永远不要让一个工具调用错误把整个程序搞崩**。

### 报错 11：`ModuleNotFoundError: No module named 'eval.tasks'; 'eval' is not a package`

- **原因**：脚本文件名 `eval.py` 和包名 `eval/` 冲突。当你 `cd eval` 后运行 `python eval.py`，Python 会把脚本自身当成 `eval` 模块，而不是 `eval` 包。
- **解决**：已修复——`eval.py` 里改成 `from tasks import TASKS`（同目录直接导入）。以后统一在**项目根目录**运行，避免脚本名/包名撞名。

### 报错 12：`AuthenticationError` / 401 `api key ... is invalid`

- **原因**：API key 填错。最常见的是复制时把占位符的 `sk-` 前缀保留了，又粘贴了带 `sk-` 的完整 key，变成 `sk-sk-...`。
- **解决**：确认 `config.py` 里的 key 以**一个** `sk-` 开头、无多余空格。快速自查：`python -c "import config; print(config.API_KEY[:7])"`，若输出 `sk-sk-` 就是重复了前缀。

### 报错 13：`ImportError: DLL load failed while importing fast_index`

- **原因**：MinGW 编译的 `.pyd` 依赖 libstdc++/libgcc 运行时 DLL，Python 运行时找不到。
- **解决**：编译时加 `-static-libgcc -static-libstdc++ -static` 静态链接，生成自包含的 `.pyd`。

### 报错 14：C++ 索引加载失败（`_HAS_CPP_INDEX` 为 False）

- **原因**：`fast_index.pyd` 在 `agent/` 子目录，代码里直接 `import fast_index` 时 `agent/` 不在 `sys.path`，找不到。
- **解决**：用包内导入 `from agent import fast_index`（`tools.py` 已修复）。且 `tools.py` 有 `try/except` 回退——加载失败会自动退回纯 Python，项目照样能跑。

---

## 三、下一步路线（M1 → M2 → M3）

### M1（已完成）：最小闭环 ✅
单步调用 → 多步循环 → 多工具 → 事实核查雏形 → 最小评估。

### M2（已完成）：记忆闭环 + 脏数据防御 + 评估 v2 ✅
- **记忆闭环**：新增 `update_user_preferences` 工具，agent 能主动把偏好写进长期记忆，下次对话复用。
- **脏数据防御**：接入真实 Amazon 数据集（234 条），保留天然缺字段的脏数据，工具层用 `.get()` 防御（见知识点 7）。
- **评估 v2**：任务集扩到 30 条分 5 类，指标拆成「成功率」+「质量分」（见知识点 8）。

> 关于"真实数据源"：M3 换成了真实 Amazon 公开数据集（luminati-io/Amazon-dataset-samples，1001 条真实商品），用 `build_dataset.py` 做 ETL 清洗后筛出 234 条。选公开数据集而不是爬京东/淘宝，是因为它**可复现、无反爬/合规风险**，且真实数据天然带脏字段（缺价格、缺描述、价格是科学计数法字符串），正好练"处理不规整数据"的能力。

### M3（已完成）：C++ 差异化模块 ✅
- 用 **pybind11 + C++** 实现了**倒排索引**（`cpp/index.cpp`），加速 `search_products` 工具：tag 精确 O(1) + name 子串 unigram 缩小候选。
- 实测 10 万条商品查询加速 19–42 倍（`python benchmark.py`）。
- 踩坑：MinGW 编译的 .pyd 依赖运行时 DLL（报错 13）、.pyd 放在子目录找不到（报错 14），都已解决并记录。

> 注：最初计划做「约束解码」，后调整为「倒排索引」。原因：真正的约束解码要 hook 推理引擎采样层，不是一个 pybind11 模块能独立完成的；倒排索引是 C++ 天然的强项，可量化、可落地。

### M4（可选）：开源 + 技术博客
- 推到 GitHub，写一篇讲"为什么 agent 的性能关键路径要用 C++"的技术博客。
- 博客重点：倒排索引实现 + 性能对比数字 + 踩坑记录。

---

## 四、面试时的"话术"备忘

- 别只说"我做了个导购 agent"，要说：**"我设计了一套原子化工具 + 多步 Planner-Executor 循环，加了预算合规硬校验和 LLM-judge 双通道评估，把幻觉率从 X 降到 Y"**。
- 别只说"我用了 DeepSeek"，要说：**"为什么选低 temperature 保证工具调用稳定、为什么工具要拆原子、为什么状态要显式化"**——这些设计判断才是考察点。
- C++ 是你的差异化：面试时主动提"我用 C++ 倒排索引把搜索工具从 O(n) 线性扫描换成索引查询，10 万条数据下加速 19–42 倍——agent 的性能关键路径在底层，纯 Python 不行"。
