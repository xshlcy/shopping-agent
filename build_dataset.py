"""真实商品数据构建脚本：Amazon 公开数据集 -> data/products.json

数据来源：luminati-io/Amazon-dataset-samples（GitHub 公开样例，1001 条真实 Amazon 商品）
  - 原始 URL：https://github.com/luminati-io/Amazon-dataset-samples
  - 数据文件：amazon-products.csv（约 6MB）
  - 字段：title / final_price / rating / reviews_count / categories / brand /
          description / top_review / currency / asin ...

为什么写这个脚本而不是手写 JSON：
  1. 真实数据一定「不规整」——价格是带引号的字符串或科学计数法、评分是字符串、
     品类是 JSON 数组字符串。要先把它们「清洗」成统一 schema，这一步本身就是
     生产 agent 的日常（接外部数据源的第一件事是 ETL 清洗）。
  2. 可复现：换一批数据 / 换更大数据集，改几个参数重跑即可，不用手改。

输出 schema（对齐 tools.py 的字段约定）：
  id / asin / name / brand / price(USD float) / currency / rating / reviews /
  category(叶子品类) / tags(搜索词) / specs(描述截断) / review_summary(评价截断)

「脏数据」策略：刻意保留数据集里天然缺 description / top_review 的真实商品，
让工具层的 .get() 防御有真对象可练——而不是手写 mock 缺字段。
"""
import csv
import io
import json
import os
import sys

# 用 jsdelivr CDN 加速（raw.githubusercontent.com 在国内慢）
DATA_URL = "https://cdn.jsdelivr.net/gh/luminati-io/Amazon-dataset-samples@main/amazon-products.csv"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "amazon-products.csv")

# 输出规模：>100 条，跨品类覆盖（Electronics 全留，其余按品类均匀取）
TARGET_CLEAN = 230
DIRTY_LIMIT = 4
DESC_LIMIT = 400   # specs 截断长度（原始 description 动辄几千字，全存会撑爆 context）
REVIEW_LIMIT = 200  # review_summary 截断长度


def _load_csv(path: str):
    csv.field_size_limit(50 * 1024 * 1024)  # description 等字段超长
    with io.open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _download() -> str:
    """下载数据到缓存，已缓存则跳过（可复现，不重复走网络）。"""
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    if not os.path.exists(CACHE):
        import urllib.request
        print(f"下载数据：{DATA_URL}")
        urllib.request.urlretrieve(DATA_URL, CACHE)
    return CACHE


def _f(v):
    """把价格/评分这类「字符串」安全转成 float，失败返回 None。"""
    if v is None:
        return None
    s = str(v).strip().strip('"').replace(",", "").strip()
    if s in ("", "None", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(v):
    """评价数转 int，失败返回 0。"""
    try:
        return int(float(str(v).strip().strip('"')))
    except (ValueError, TypeError):
        return 0


def _cats(v):
    """品类字段是 JSON 数组字符串，解析成 [顶级, ..., 叶子]。"""
    try:
        c = json.loads(v)
        return c if isinstance(c, list) else []
    except (ValueError, TypeError):
        return []


def _parse(row):
    """一行原始数据 -> 规整后的商品 dict（或 None 表示该行不可用）。"""
    title = (row.get("title") or "").strip()
    price = _f(row.get("final_price"))
    rating = _f(row.get("rating"))
    reviews = _i(row.get("reviews_count"))
    cats = _cats(row.get("categories"))
    brand = (row.get("brand") or "").strip()
    desc = (row.get("description") or "").strip()
    top_review = (row.get("top_review") or "").strip()
    currency = (row.get("currency") or "").strip()

    if not title:
        return None
    # 只保留美元商品，保证价格口径统一、可比较
    if currency != "USD":
        return None

    p = {
        "asin": (row.get("asin") or "").strip(),
        "name": title,
        "brand": brand or "无品牌",
        "currency": "USD",
        "category": cats[-1] if cats else "未分类",
        # tags：顶级品类 + 各级品类 + 品牌，都是搜索词
        "tags": [c for c in cats if c] + ([brand] if brand else []),
    }
    if price is not None:
        p["price"] = round(price, 2)
    if rating is not None:
        p["rating"] = rating
    if reviews:
        p["reviews"] = reviews
    if desc:
        p["specs"] = desc[:DESC_LIMIT]
    if top_review:
        p["review_summary"] = top_review[:REVIEW_LIMIT]
    return p


def _is_clean(p):
    """干净商品 = 核心字段（价格/评分/评价数）+ 描述 + 评价摘要全齐全。"""
    return all(k in p for k in ("price", "rating", "reviews", "specs", "review_summary"))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else _download()
    rows = _load_csv(path)

    parsed = [p for p in (_parse(r) for r in rows) if p]
    # 核心字段「价格」缺失的商品无法被推荐，ETL 阶段直接过滤（并单独报告数量）
    n_no_price = sum(1 for p in parsed if "price" not in p)
    parsed = [p for p in parsed if "price" in p]
    clean = [p for p in parsed if _is_clean(p)]
    dirty = [p for p in parsed if not _is_clean(p)]

    # Electronics 全留（导购 demo 里科技类最自然），其余按顶级品类均匀取
    electronics = [p for p in clean if p["tags"] and p["tags"][0] == "Electronics"]
    others = [p for p in clean if not (p["tags"] and p["tags"][0] == "Electronics")]
    # 稳定排序：按 asin，保证每次重跑结果一致（可复现）
    others.sort(key=lambda p: p["asin"])

    take_others = max(0, TARGET_CLEAN - len(electronics))
    selected = electronics + others[:take_others]
    selected.sort(key=lambda p: p["asin"])

    # 脏数据：取真实缺字段的商品（缺价格/评分，或缺描述/评价），上限 DIRTY_LIMIT
    dirty = dirty[:DIRTY_LIMIT]

    # 合并 + 分配连续 id
    all_products = selected + dirty
    for i, p in enumerate(all_products, 1):
        p["id"] = i

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "products.json")
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)

    n_dirty = len(dirty)
    print(f"过滤掉缺价格商品：{n_no_price} 条（核心字段缺失，无法被推荐）")
    print(f"解析可用商品：{len(parsed)}（其中干净 {len(clean)}、天然脏 {len(dirty)}）")
    print(f"选中商品：{len(all_products)}（干净 {len(selected)} + 脏 {n_dirty}）")
    print(f"  脏数据缺字段分布：缺 specs={sum(1 for p in all_products if 'specs' not in p)}，"
          f"缺 review_summary={sum(1 for p in all_products if 'review_summary' not in p)}")
    print(f"输出：{out_path}")


if __name__ == "__main__":
    main()
