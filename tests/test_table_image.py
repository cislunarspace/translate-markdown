"""预处理与合并测试 — 保护表格与图片（issue #5 切片 4）"""

import textwrap

from main import (
    Block,
    TranslationResult,
    TranslationUnit,
    merge_results,
    preprocess,
)


# ---------------------------------------------------------------------------
# preprocess —— 表格识别
# ---------------------------------------------------------------------------


def test_table_is_single_translation_unit():
    """Markdown 表格（多行含 |）整体作为一个 TranslationUnit。"""
    source = textwrap.dedent("""\
        Some text.

        | Name | Age |
        | --- | --- |
        | Alice | 30 |
        | Bob | 25 |

        More text.
    """).rstrip("\n")

    blocks, units, ic_map = preprocess(source)

    # 块：Some text.、空行、表格整体、空行、More text.
    assert len(blocks) == 5

    # 表格块的 original 包含所有表格行
    table_block = blocks[2]
    assert "| Name | Age |" in table_block.original
    assert "| --- | --- |" in table_block.original
    assert "| Alice | 30 |" in table_block.original
    assert "| Bob | 25 |" in table_block.original

    # 表格整体作为一个 TranslationUnit
    assert table_block.unit_id is not None
    table_unit = next(u for u in units if u.unit_id == table_block.unit_id)
    assert "| Name | Age |" in table_unit.original
    assert "| Alice | 30 |" in table_unit.original

    # 总共 3 个 TranslationUnit：Some text.、表格、More text.（空行不生成 unit）
    translatable_blocks = [b for b in blocks if b.unit_id is not None]
    assert len(translatable_blocks) == len(units)


def test_table_columns_preserved_in_output():
    """表格结构在输出中不错位——列数、分隔行保持不变。"""
    source = "| A | B |\n| --- | --- |\n| 1 | 2 |"

    blocks, units, ic_map = preprocess(source)

    # 整个表格作为一个 unit
    assert len(units) == 1
    table_unit = units[0]
    assert "| A | B |" in table_unit.original
    assert "| --- | --- |" in table_unit.original

    # 模拟 LLM 翻译：保持表格行结构
    results = [
        TranslationResult(unit_id=0, translated="| A | B |\n| --- | --- |\n| 一 | 二 |")
    ]

    output = merge_results(blocks, results, ic_map)

    assert "| A | B |" in output
    assert "| --- | --- |" in output
    assert "| 一 | 二 |" in output
    # 列数不变
    lines = [l for l in output.split("\n") if l.strip()]
    for line in lines:
        # 每行都有 3 个 |（2 列表格）
        assert line.count("|") == 3


def test_table_with_inline_code():
    """表格中的行内代码被替换为占位符，在输出中保持不译。"""
    source = "| Function | Usage |\n| --- | --- |\n| `print()` | output |"

    blocks, units, ic_map = preprocess(source)

    # 表格作为一个 unit
    assert len(units) == 1
    table_unit = units[0]
    assert "{{IC_0}}" in table_unit.original
    assert "`print()`" not in table_unit.original
    assert ic_map[0] == ["print()"]

    # 模拟 LLM 翻译保留占位符
    results = [
        TranslationResult(unit_id=0, translated="| Function | Usage |\n| --- | --- |\n| {{IC_0}} | 输出 |")
    ]

    output = merge_results(blocks, results, ic_map)

    assert "`print()`" in output
    assert "{{IC_0}}" not in output
    assert "| 输出 |" in output


# ---------------------------------------------------------------------------
# preprocess —— 图片识别
# ---------------------------------------------------------------------------


def test_image_path_protected():
    """图片路径作为保护内容保留不变，alt 文本作为可译内容。"""
    source = "![Logo](/images/logo.png)"

    blocks, units, ic_map = preprocess(source)

    assert len(units) == 1
    unit = units[0]
    # alt 文本保留在原位
    assert "Logo" in unit.original
    # 路径被替换为占位符
    assert "{{IP_0}}" in unit.original
    assert "/images/logo.png" not in unit.original

    # 路径存储在 block 的 ip_paths 中
    assert blocks[0].ip_paths == ["/images/logo.png"]


def test_image_alt_text_translated():
    """图片 alt 文本在翻译结果中有 [translated] 前缀。"""
    source = "![Logo](/images/logo.png)"

    blocks, units, ic_map = preprocess(source)

    # MockLLMClient 行为：给原文加 [translated] 前缀
    llm_results = [
        TranslationResult(unit_id=0, translated="[translated] ![Logo]({{IP_0}})")
    ]

    output = merge_results(blocks, llm_results, ic_map)

    # alt 文本被翻译
    assert "[translated]" in output
    assert "Logo" in output
    # 路径不变
    assert "/images/logo.png" in output
    assert "{{IP_0}}" not in output


def test_image_path_unchanged_in_output():
    """图片路径在输出中完全不变。"""
    source = "![Photo](https://example.com/pic.jpg)"

    blocks, units, ic_map = preprocess(source)

    results = [
        TranslationResult(unit_id=0, translated="[translated] ![Photo]({{IP_0}})")
    ]

    output = merge_results(blocks, results, ic_map)

    assert "https://example.com/pic.jpg" in output
    assert "{{IP_0}}" not in output


def test_multiple_images():
    """一行中有多个图片引用，各自路径独立保护。"""
    source = "![A](/a.png) and ![B](/b.png)"

    blocks, units, ic_map = preprocess(source)

    assert len(units) == 1
    unit = units[0]
    assert "{{IP_0}}" in unit.original
    assert "{{IP_1}}" in unit.original
    assert blocks[0].ip_paths == ["/a.png", "/b.png"]

    # MockLLMClient 翻译
    results = [
        TranslationResult(
            unit_id=0,
            translated="[translated] ![A]({{IP_0}}) and ![B]({{IP_1}})"
        )
    ]

    output = merge_results(blocks, results, ic_map)

    assert "/a.png" in output
    assert "/b.png" in output
    assert "{{IP_" not in output


def test_image_with_inline_code():
    """图片引用和行内代码共存时，各自独立保护。"""
    source = "![`code`](/img.png) uses `foo()`."

    blocks, units, ic_map = preprocess(source)

    assert len(units) == 1
    unit = units[0]
    # 行内代码被替换
    assert "{{IC_0}}" in unit.original  # `code`
    assert "{{IC_1}}" in unit.original  # `foo()`
    # 图片路径被替换
    assert "{{IP_0}}" in unit.original
    assert "/img.png" not in unit.original

    assert blocks[0].ip_paths == ["/img.png"]
    assert ic_map[0] == ["code", "foo()"]

    # MockLLMClient 翻译
    results = [
        TranslationResult(
            unit_id=0,
            translated="[translated] ![{{IC_0}}]({{IP_0}}) uses {{IC_1}}."
        )
    ]

    output = merge_results(blocks, results, ic_map)

    assert "`code`" in output
    assert "`foo()`" in output
    assert "/img.png" in output
    assert "{{IC_" not in output
    assert "{{IP_" not in output


# ---------------------------------------------------------------------------
# 端到端：表格 + 图片混合场景
# ---------------------------------------------------------------------------


def test_table_and_image_in_document():
    """包含表格和图片的完整文档，表格结构不错位，图片路径不变。"""
    source_lines = [
        "# Title",
        "",
        "![Banner](/images/banner.png)",
        "",
        "| Item | Price |",
        "| --- | --- |",
        "| Apple | $1 |",
        "| Banana | $2 |",
        "",
        "![Footer](/images/footer.jpg)",
    ]
    source = "\n".join(source_lines)

    blocks, units, ic_map = preprocess(source)

    # 找到表格块
    table_blocks = [
        b for b in blocks
        if "| Item |" in (b.original or "")
    ]
    assert len(table_blocks) == 1
    table_block = table_blocks[0]
    assert "| --- | --- |" in table_block.original
    assert "| Apple |" in table_block.original

    # 找到图片块
    img_blocks = [b for b in blocks if b.ip_paths]
    assert len(img_blocks) == 2
    assert img_blocks[0].ip_paths == ["/images/banner.png"]
    assert img_blocks[1].ip_paths == ["/images/footer.jpg"]

    # 模拟完整翻译（MockLLMClient 行为）
    results = [
        TranslationResult(unit_id=u.unit_id, translated=f"[translated] {u.original}")
        for u in units
    ]

    output = merge_results(blocks, results, ic_map)

    # 表格结构保留
    assert "| Item | Price |" in output
    assert "| --- | --- |" in output
    assert "| Apple | $1 |" in output
    assert "| Banana | $2 |" in output

    # 图片路径不变
    assert "/images/banner.png" in output
    assert "/images/footer.jpg" in output
    assert "{{IP_" not in output

    # alt 文本被翻译
    assert "[translated]" in output


def test_table_after_code_block():
    """代码块之后的表格仍正确识别为单个 TranslationUnit。"""
    source = textwrap.dedent("""\
        ```python
        x = 1
        ```

        | A | B |
        | --- | --- |
        | 1 | 2 |
    """).rstrip("\n")

    blocks, units, ic_map = preprocess(source)

    # 第一个块是保护块（代码块）
    assert blocks[0].translated is None
    assert "```python" in blocks[0].original

    # 找到表格 unit
    table_units = [u for u in units if "| A |" in u.original]
    assert len(table_units) == 1
    assert "| --- | --- |" in table_units[0].original
