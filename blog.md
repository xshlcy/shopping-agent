# 为什么我用 C++ 给 LLM Agent 的搜索工具提速了 40 倍

> 一个 C++ 背景的人，做 LLM agent 时的挣扎与解法。

## 一、LLM 时代，C++ 还有位置吗？

我熟悉的语言是 C++，但这两年做 LLM agent 的人都在写 Python。一开始我也很慌：`langchain`、`openai`、`pydantic`……满世界都是 Python，我的 C++ 是不是过时了？

做了一阵子 agent 后我发现一件事：**agent 的性能瓶颈，往往不在模型推理，而在它调用的工具。**

一个典型的 agent 循环是：模型决定"下一步做什么" → 调用工具（搜索、查库、调 API）→ 拿到结果 → 再决策。模型推理那几百毫秒是固定的，但工具执行是**你的代码**——这里有一整块可以优化的空间，而这块恰恰是 C++ 的主场。

## 二、瓶颈不在模型，在工具

我做的电商导购 agent，`search_products` 工具长这样（Python 朴素实现）：

```python
def search_products(keyword, max_price):
    return [p for p in PRODUCTS
            if keyword in p["name"] or any(keyword in t for t in p["tags"])
            if p["price"] <= max_price]
```

这是 O(n) 线性扫描。30 条商品时没问题，但商品库到 10 万、100 万条呢？每次工具调用都要扫一遍全表——**模型每问一次"找找降噪耳机"，你的 Python 就要在几十万条数据里逐条 `in` 匹配。**

而且 agent 是会**多步反复调工具**的：搜索 → 看详情 → 看评价 → 对比，一个任务可能触发十几次搜索。O(n) 的代价被放大十几倍。

## 三、倒排索引：从 O(n) 到 O(候选)

我熟悉搜索引擎的经典结构，于是给这个工具写了个 C++ 倒排索引：

1. **tag 精确索引**：`"降噪" -> [商品1, 商品2, ...]`，哈希表 O(1) 命中。
2. **name 的 unigram 索引**：把商品名按 UTF-8 字符拆成单字，`"降" -> [所有名字含"降"的商品]`。查询"降噪耳机"时，先用第一个字"降"的倒排列表缩小候选集，再对候选做精确 `find` 验证。

核心就一百多行 C++：

```cpp
class ProductIndex {
    std::unordered_map<std::string, std::vector<int>> tag_index;     // tag -> ids
    std::unordered_map<std::string, std::vector<int>> unigram_index; // char -> ids

    std::vector<int> search(const std::string& keyword, double max_price) {
        // 1. tag 精确匹配 O(1)
        // 2. name 子串：用 keyword 首字符的倒排列表做候选，再 find 验证
    }
};
```

关键点在于：**unigram 索引把"子串匹配"这个看似只能线性扫的操作，变成了"先 O(1) 拿候选、再精确验证"**。keyword 越稀有的字，候选集越小，加速越狠。

## 四、pybind11：让 C++ 和 Python 无缝对接

C++ 写好只是第一步，agent 是 Python 写的。我用 pybind11 把类绑定成 Python 模块：

```cpp
PYBIND11_MODULE(fast_index, m) {
    py::class_<ProductIndex>(m, "ProductIndex")
        .def(py::init<>())
        .def("build", &ProductIndex::build)
        .def("search", &ProductIndex::search);
}
```

Python 侧一行就能用：

```python
from agent import fast_index
idx = fast_index.ProductIndex()
idx.build(names, prices, tags)
ids = idx.search("降噪", 1000)
```

而且我做了**优雅降级**：`tools.py` 里 `try/except` 加载 C++ 模块，加载失败自动回退纯 Python。所以 C++ 是"可选加速"，不是"硬依赖"——缺了 .pyd 项目照样跑，只是慢一点。

## 五、踩坑记录

**坑 1：MinGW 编译的 .pyd 一 import 就崩。** `ImportError: DLL load failed`。原因是 MinGW 编译的扩展依赖 libstdc++/libgcc 运行时 DLL，Python 找不到。解法是编译时加 `-static-libgcc -static-libstdc++ -static` 静态链接，生成自包含的 .pyd。

**坑 2：.pyd 放子目录 import 不到。** 编译产物放在 `agent/` 目录，直接 `import fast_index` 找不到，因为 `agent/` 不在 `sys.path`。解法是改成包内导入 `from agent import fast_index`。

这两个坑都是"你真的自己编译过"才会遇到的那种——恰恰是它们的价值。

## 六、结果

10 万条模拟商品，同一搜索需求，两种实现对比：

| 关键词 | C++(微秒) | Python(微秒) | 加速比 |
|---|---|---|---|
| 降噪 | 1768 | 37673 | **21x** |
| 音箱 | 1991 | 83306 | **42x** |
| 机械键盘 | 4245 | 80071 | **19x** |
| 苹果（稀有词） | 1.5 | 86795 | **59044x** |

常规查询 **19–42 倍**，稀有词甚至更高。索引构建只需 0.27 秒，一次性成本。

## 七、反思

写这个模块，我最大的收获不是"学会了 pybind11"，而是想通了一件事：

**LLM agent 的竞争，会从"谁的 prompt 写得好"逐渐下移到"谁的工程能力强"。** 当大家都在调同一个模型、用同一个框架时，工具执行效率、状态管理、评估体系这些"底下的东西"才是分水岭。

C++ 没死，它只是从"写业务"退到了"写关键路径"——而这恰恰是它最擅长、也最值钱的位置。

---

*项目地址：见仓库 README。含完整代码、30 任务评估集、性能对比脚本，以及一份「面试复盘」文档（踩坑 + 设计决策 + 高频问答）。*
