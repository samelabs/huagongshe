"""文本归一小工具（无依赖，供 HTTP/service 层共用）。"""

from __future__ import annotations

_BS = "\\"


def like_literal(value: str) -> str:
    """用户输入按字面进 LIKE/ILIKE。

    % / _ / 反斜杠是数据不是通配符 —— 转义后语义才是「包含这些字符的串」。
    PG LIKE 默认转义符即反斜杠, 无需 ESCAPE 子句。
    """
    return (value.replace(_BS, _BS + _BS)
            .replace("%", _BS + "%").replace("_", _BS + "_"))
