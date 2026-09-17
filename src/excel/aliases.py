"""Configurable header aliases for layout adapters. Add languages here, not in classifiers."""

from __future__ import annotations

import re

QUESTION_ALIASES = (
    "question",
    "frage",
    "item",
    "statement",
    "item text",
    "问题",
    "題目",
    "题目",
    "题项",
    "題項",
    "問項",
)

CODEBOOK_VARIABLE_ALIASES = (
    "variable",
    "var_name",
    "varname",
    "变量",
    "变量名",
    "欄位",
    "栏位",
)

CODEBOOK_CODE_ALIASES = (
    "code",
    "代码",
    "編碼",
    "编码",
)

CODEBOOK_LABEL_ALIASES = (
    "value_label",
    "value label",
    "label",
    "meaning",
    "beschreibung",
    "bezeichnung",
    "标签",
    "標籤",
    "含义",
    "含義",
    "值标签",
)

KV_LEFT_ALIASES = (
    "key",
    "field",
    "label",
    "attribute",
    "item",
    "字段",
    "欄位",
    "栏位",
    "属性",
    "屬性",
)

KV_RIGHT_ALIASES = (
    "value",
    "val",
    "content",
    "answer",
    "值",
    "内容",
    "內容",
)

PERSONA_KEYS = frozenset({"persona", "persona_name"})
PERSONA_ID_KEYS = frozenset({"persona_id", "personaid"})


def aliases_regex(aliases: tuple[str, ...], *, as_word: bool = False) -> re.Pattern[str]:
    parts: list[str] = []
    for alias in aliases:
        escaped = re.escape(alias.strip())
        escaped = escaped.replace(r"\ ", r"[\s_]*")
        if as_word:
            escaped = rf"\b{escaped}\b"
        parts.append(escaped)
    return re.compile("|".join(parts), re.I)
