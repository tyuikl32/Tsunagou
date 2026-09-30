"""The console's Chinese for the protocol's tokens.

These are the rules the table itself has to keep: a word per token, short enough to
sit in a table cell, and actually Chinese. A missing token is fine — the page shows
the raw token then — but a *wrong* or long one is not, because nobody reads the
table before shipping a value.
"""

from __future__ import annotations

from tsunagou.console.glossary import GLOSSARY, GLOSSARY_VERSION, public
from tsunagou.shared_kernel.baseline import (
    ADMISSION_CAPABILITIES,
    BASELINE_CAPABILITIES,
    OPERATIONAL_CAPABILITIES,
)

# 表格单元格里放得下的长度。「已答复」「等待中」是 3 个字，「共享目录」「重试后拿到」是 5 个；
# 留一格余地给以后实在压不下去的词 —— 但超过这个数就该先想想能不能压。
MAX_WORD_LENGTH = 6

# 这几个不是词表自己挑的词，而是界面上早就在用的说法（Agent 管理页的卡片标题就是
# 「主 Agent」/「子 Agent」，左栏卡片也是）。改短反而与别处不一致，所以明确记为例外。
DESIGN_WORDS = {("agent_role", "main"), ("agent_role", "worker")}


def test_every_domain_has_short_chinese_words() -> None:
    for domain, entries in GLOSSARY.items():
        assert entries, f"{domain} 是空域：要么补词，要么删掉这个域"
        for token, word in entries.items():
            assert token and token == token.strip(), (domain, token)
            assert word and word == word.strip(), (domain, token, word)
            assert any("\u4e00" <= char <= "\u9fff" for char in word), f"{domain}.{token} 不是中文：{word}"
            if (domain, token) in DESIGN_WORDS:
                continue
            assert len(word) <= MAX_WORD_LENGTH, f"{domain}.{token} 太长：{word}（请先想能不能压缩）"


def test_domains_are_looked_up_by_display_not_by_field_name() -> None:
    # 域是"给人看的那一栏"，不是出口字段名 —— message_status 不属于某个出口，
    # 所以这里只检查命名风格：小写下划线，不带点号（点号会被 state 的路径读取当成层级）。
    for domain in GLOSSARY:
        assert domain == domain.lower()
        assert "." not in domain and " " not in domain, domain


def test_public_hands_out_a_copy() -> None:
    first = public()
    first["domains"]["lifecycle"]["active"] = "被改坏了"
    assert public()["domains"]["lifecycle"]["active"] == "进行中"
    assert first["version"] == GLOSSARY_VERSION


def test_the_two_capability_columns_are_the_baseline_itself() -> None:
    """Agent 管理那两栏不是另抄的一份名单：共有哪些、怎么分两栏，都问 shared_kernel。

    后台的 missing_admission / missing_operational 只说"缺哪几项"，页面上那两栏的
    名字与顺序全从这两张表来 —— 所以它们必须与基线一一对应，多一项或少一项都会
    让页面画出后端根本不会说的名字。
    """
    admission = GLOSSARY["capability_admission"]
    operational = GLOSSARY["capability_operational"]

    assert tuple(admission) == ADMISSION_CAPABILITIES
    assert tuple(operational) == OPERATIONAL_CAPABILITIES
    assert set(admission) | set(operational) == set(BASELINE_CAPABILITIES)


def test_a_denial_code_is_keyed_by_its_head_only() -> None:
    """拒绝码可以带参数（`resource_conflict:file:src/x.py`），页面只查冒号前那截。"""
    for code in GLOSSARY["denial_reason"]:
        assert ":" not in code, code
