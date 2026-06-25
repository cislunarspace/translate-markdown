"""后端预处理与合并测试（issue #4 切片 3：保护代码块与行内代码）"""

import textwrap

from main import (
    Block,
    TranslationResult,
    TranslationUnit,
    merge_results,
    preprocess,
)


# ---------------------------------------------------------------------------
# preprocess —— 代码块识别
# ---------------------------------------------------------------------------


def test_fenced_code_block_is_protected():
    """fenced code block（```）整体作为一个保护块，不生成 TranslationUnit。"""
    source = textwrap.dedent("""\
        Hello world.

        ```python
        print("hi")
        x = 1 + 2
        ```
    """).rstrip("\n")

    blocks, units, ic_map = preprocess(source)

    # 第一个块是普通段落
    assert blocks[0].original == "Hello world."

    # 第二个块是空行，第三个块是保护块（代码块整体）
    code_block = blocks[2]
    assert "```python" in code_block.original
    assert 'print("hi")' in code_block.original
    assert "x = 1 + 2" in code_block.original
    assert code_block.translated is None

    # 只有普通段落和空行生成了 TranslationUnit（代码块不生成）
    assert len(units) == 2
    assert units[0].original == "Hello world."
    assert units[1].original == ""


def test_tilde_fence_is_also_protected():
    """~~~ 围栏的代码块同样被识别为保护块。"""
    source = textwrap.dedent("""\
        ~~~bash
        echo hello
        ~~~
    """).rstrip("\n")

    blocks, units, ic_map = preprocess(source)

    assert len(blocks) == 1
    assert "~~~bash" in blocks[0].original
    assert "echo hello" in blocks[0].original
    assert len(units) == 0


def test_code_block_surrounding_text_is_translated():
    """代码块前后的普通段落仍生成 TranslationUnit。"""
    source = textwrap.dedent("""\
        Before text.

        ```
        code line
        ```

        After text.
    """).rstrip("\n")

    blocks, units, ic_map = preprocess(source)

    # 五个块：Before text、空行、代码块、空行、After text
    assert len(blocks) == 5
    assert blocks[0].original == "Before text."
    assert "```" in blocks[2].original
    assert blocks[4].original == "After text."

    # 四个 TranslationUnit：两个段落 + 两个空行（代码块不生成 unit）
    assert len(units) == 4
    assert units[0].original == "Before text."
    assert units[1].original == ""
    assert units[2].original == ""
    assert units[3].original == "After text."


# ---------------------------------------------------------------------------
# preprocess —— 行内代码占位符
# ---------------------------------------------------------------------------


def test_inline_code_replaced_with_placeholder():
    """行内代码被替换为占位符 {{IC_0}}，原始代码记录在 ic_map 中。"""
    source = "Use `print()` to debug."

    blocks, units, ic_map = preprocess(source)

    assert len(units) == 1
    assert "{{IC_0}}" in units[0].original
    assert "`print()`" not in units[0].original
    assert ic_map[0] == ["print()"]


def test_multiple_inline_codes_on_one_line():
    """一行中有多个行内代码，各自替换为独立占位符。"""
    source = "Call `foo()` and `bar()` together."

    blocks, units, ic_map = preprocess(source)

    assert len(units) == 1
    assert "{{IC_0}}" in units[0].original
    assert "{{IC_1}}" in units[0].original
    assert ic_map[0] == ["foo()", "bar()"]


# ---------------------------------------------------------------------------
# merge_results —— 占位符回填
# ---------------------------------------------------------------------------


def test_merge_restores_inline_code():
    """merge_results 将翻译结果中的占位符回填为原始行内代码。"""
    source = "Use `print()` to debug."
    blocks, units, ic_map = preprocess(source)

    # 模拟 LLM 翻译：假设 LLM 保留了占位符
    results = [TranslationResult(unit_id=0, translated="使用 {{IC_0}} 进行调试。")]

    output = merge_results(blocks, results, ic_map)

    assert "`print()`" in output
    assert "{{IC_0}}" not in output


# ---------------------------------------------------------------------------
# 端到端：代码块在输出中完全不变
# ---------------------------------------------------------------------------


def test_code_block_content_unchanged_in_output():
    """包含代码块的文档，代码块内容在合并输出中完全不变。"""
    source_lines = [
        "Some text.",
        "",
        "```python",
        'print("hello")',
        "x = 1 + 2",
        "```",
        "",
        "More text.",
    ]
    source = "\n".join(source_lines)

    blocks, units, ic_map = preprocess(source)

    # 模拟 LLM 翻译（MockLLMClient 行为：每个 unit 加前缀）
    results = [
        TranslationResult(unit_id=i, translated=f"[translated] {u.original}")
        for i, u in enumerate(units)
    ]

    output = merge_results(blocks, results, ic_map)

    # 代码块内容原样保留
    assert '```python\nprint("hello")\nx = 1 + 2\n```' in output
    # 翻译结果也正确
    assert "[translated] Some text." in output
    assert "[translated] More text." in output


def test_inline_code_preserved_in_output():
    """包含行内代码的文档，行内代码在输出中完全不变。"""
    source = "Use `foo()` to start."

    blocks, units, ic_map = preprocess(source)

    # 模拟 LLM 翻译：翻译时占位符被保留
    results = [TranslationResult(unit_id=0, translated="使用 {{IC_0}} 来启动。")]

    output = merge_results(blocks, results, ic_map)

    assert "`foo()`" in output
    assert "{{IC_0}}" not in output
    assert output == "使用 `foo()` 来启动。"


def test_paragraph_with_inline_code_and_code_block():
    """段落含行内代码 + fenced code block 的混合场景。"""
    source = "\n".join([
        "Run `main.py` to start.",
        "",
        "```",
        "x = 42",
        "```",
        "",
        "Then call `run()` to finish.",
    ])

    blocks, units, ic_map = preprocess(source)

    # 五个块：段落、空行、代码块、空行、段落
    assert len(blocks) == 5
    assert len(units) == 4  # 两个段落 + 两个空行

    # 行内代码占位符在 units[0] 和 units[3]（跳过空行 unit）
    assert "{{IC_0}}" in units[0].original  # main.py
    assert "{{IC_0}}" in units[3].original  # run()

    # 模拟 LLM 翻译
    results = [
        TranslationResult(unit_id=0, translated="运行 {{IC_0}} 来启动。"),
        TranslationResult(unit_id=1, translated=""),
        TranslationResult(unit_id=2, translated=""),
        TranslationResult(unit_id=3, translated="然后调用 {{IC_0}} 来完成。"),
    ]

    output = merge_results(blocks, results, ic_map)

    assert "`main.py`" in output
    assert "`run()`" in output
    assert "x = 42" in output
    assert "{{IC_" not in output


def test_display_math_is_single_protected_block():
    """$$...$$ 包裹的行间公式作为整体保护块，不拆分、不生成翻译单元。"""
    source = textwrap.dedent("""\
        Some text.

        $$
        a + b = c
        d + e = f
        $$

        More text.
    """)

    blocks, units, ic_map = preprocess(source)

    # 定位公式块（保护块，unit_id 为 None）
    math_blocks = [b for b in blocks if b.unit_id is None and "$$" in b.original]
    assert len(math_blocks) == 1

    math_block = math_blocks[0]
    assert "a + b = c" in math_block.original
    assert "d + e = f" in math_block.original

    # 公式内部不生成 TranslationUnit
    math_unit_ids = {u.unit_id for u in units if "a + b" in u.original or "d + e" in u.original}
    assert math_unit_ids == set()

    # 合并输出保持公式原样
    results = [
        TranslationResult(unit_id=u.unit_id, translated=f"[translated] {u.original}")
        for u in units
    ]
    output = merge_results(blocks, results, ic_map)

    assert "a + b = c" in output
    assert "d + e = f" in output
    assert output.count("$$") == 2
