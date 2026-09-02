"""merge_entry: CPP 正向, CAS 页字段级补缺(0902 P3a)。
CPP 值恒胜; 只补 CPP 缺的 key; reagents 块 CAS 独有整体并入。
"""
from __future__ import annotations

from typing import Any


def merge_entry(cpp: dict[str, Any], cas_e: dict[str, Any]) -> dict[str, Any]:
    """字段级合并: cpp 为主体, cas 只补缺。

    - dict 区(props/safety): key 级合并, cpp 值恒胜, 只补 cpp 没有的 key
    - list 区(basic/aliases): 追加 cpp 中不存在的 [k,v] 行 / 别名字符串
    - reagents: CAS 独有块, 整体并入(cpp 无此 key)
    - 其余 cpp 独有 key(global_distribution/reagent_prices/prose...)不动
    """
    merged = dict(cpp)
    for key, cas_val in cas_e.items():
        if key not in merged or merged[key] in (None, {}, []):
            # cpp 缺该块(如 reagents)或为空 → 整块取 CAS
            if cas_val not in (None, {}, []):
                merged[key] = cas_val
            continue
        cpp_val = merged[key]
        if isinstance(cpp_val, dict) and isinstance(cas_val, dict):
            for k, v in cas_val.items():
                if k not in cpp_val:
                    cpp_val[k] = v
        elif isinstance(cpp_val, list) and isinstance(cas_val, list):
            if cpp_val and isinstance(cpp_val[0], list) and cas_val and isinstance(cas_val[0], list):
                # basic: [k, v] 行, 同 key 不重复
                have = {row[0] for row in cpp_val if len(row) >= 1}
                for row in cas_val:
                    if len(row) >= 2 and row[0] not in have:
                        cpp_val.append(row)
            elif all(isinstance(x, str) for x in cpp_val) and all(isinstance(x, str) for x in cas_val):
                # aliases: 字符串表去重追加
                have = set(cpp_val)
                for x in cas_val:
                    if x not in have:
                        cpp_val.append(x)
            # 其他形态(list of dict 如 prose/reagents): cpp 已有即 cpp 胜, 不动
    return merged
