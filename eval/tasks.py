"""评估任务集：30 条真实风格的用户需求，按 5 类划分。

分类的意义：不同类任务考察 agent 不同能力，最后能分别看"哪类最弱"，
这就是评估的价值——不是给一个笼统分数，而是定位短板。

  搜索推荐   —— 多步搜索 + 预算/场景约束 + 给出推荐
  对比       —— 需要查多个商品详情并横向比较
  评价       —— 需要调用 get_reviews 才下结论
  偏好记忆   —— 需要读/写用户偏好
  边界负例   —— 查不到/超低预算，正确行为是"如实说找不到"，而非编造

注意：商品库是英文 Amazon 真实数据（价格美元），任务里的中文品类/品牌，
agent 需在调用 search_products 时翻译成英文关键词。对比/评价类任务直接
点名了真实存在的商品（英文名），方便确定性检索。
"""

TASKS = [
    # ---- 搜索推荐（10）----
    {"query": "帮我找 100 美元以内的蓝牙音箱，推荐 2-3 款", "category": "搜索推荐"},
    {"query": "想买个 30 美元以下的无线耳机", "category": "搜索推荐"},
    {"query": "推荐一款 200 美元左右的电子书阅读器", "category": "搜索推荐"},
    {"query": "帮我找 150 美元以内的外置硬盘", "category": "搜索推荐"},
    {"query": "想买个 150 美元以内的 Wi-Fi 路由器", "category": "搜索推荐"},
    {"query": "推荐一款 50 美元以内的蓝牙耳机", "category": "搜索推荐"},
    {"query": "帮我找个 20 美元以内的充电线", "category": "搜索推荐"},
    {"query": "想买个 100 美元以内的游戏耳机", "category": "搜索推荐"},
    {"query": "推荐一款 350 美元以内的智能手表", "category": "搜索推荐"},
    {"query": "帮我找个大容量的移动硬盘，150 美元左右", "category": "搜索推荐"},

    # ---- 对比（5）----
    {"query": "帮我对比一下 JBL Charge 4 和 BUGANI 这两款蓝牙音箱", "category": "对比"},
    {"query": "Seagate Ultra Touch SSD 和 Seagate Expansion 18TB 硬盘哪个更适合备份", "category": "对比"},
    {"query": "对比一下 Razer Kraken 游戏耳机和 Trucker Bluetooth 耳机", "category": "对比"},
    {"query": "Microsoft Wedge 键盘和 R-Go Split 键盘有什么区别", "category": "对比"},
    {"query": "MusiBaby 和 Volkano 这两款蓝牙音箱哪个好", "category": "对比"},

    # ---- 评价（5）----
    {"query": "JBL Charge 4 怎么样，值得买吗", "category": "评价"},
    {"query": "Razer Kraken 游戏耳机的口碑怎么样", "category": "评价"},
    {"query": "Seagate Ultra Touch SSD 值得这个价吗", "category": "评价"},
    {"query": "Kobo Libra 2 好用吗", "category": "评价"},
    {"query": "Microsoft Wedge 键盘的评价如何", "category": "评价"},

    # ---- 偏好记忆（5）----
    {"query": "我喜欢 Seagate 这个品牌，帮我推荐一款硬盘", "category": "偏好记忆"},
    {"query": "我预算 100 美元买蓝牙音箱，顺便帮我记住这个偏好", "category": "偏好记忆"},
    {"query": "给我推荐适合送给朋友当礼物的东西", "category": "偏好记忆"},
    {"query": "记住我喜欢性价比高的东西，然后推荐个键盘", "category": "偏好记忆"},
    {"query": "根据我保存的偏好，帮我推荐一个耳机", "category": "偏好记忆"},

    # ---- 边界负例（5）----
    {"query": "帮我找 5 美元以下的蓝牙耳机", "category": "边界负例"},
    {"query": "有 10 美元的苹果电脑吗", "category": "边界负例"},
    {"query": "推荐一款 3 美元的机械键盘", "category": "边界负例"},
    {"query": "有没有 2 美元的智能手表", "category": "边界负例"},
    {"query": "帮我找一个叫 XYZ-999 的商品", "category": "边界负例"},
]
