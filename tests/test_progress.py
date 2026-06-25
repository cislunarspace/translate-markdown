"""GUI 进度回调与错误处理测试（issue #8 切片 7）"""

import textwrap
from pathlib import Path

from main import MockLLMClient, translate_document


# ---------------------------------------------------------------------------
# 进度回调测试
# ---------------------------------------------------------------------------


def test_on_progress_called_for_each_unit(tmp_path):
    """translate_document 为每个单元调用 on_progress 回调。"""
    source = tmp_path / "doc.md"
    source.write_text(
        textwrap.dedent("""\
            Line one.
            Line two.
            Line three.
        """),
        encoding="utf-8",
    )

    progress_calls: list[tuple[int, int, int]] = []
    log_messages: list[str] = []

    translate_document(
        source,
        MockLLMClient(),
        on_progress=lambda c, t, uid: progress_calls.append((c, t, uid)),
        on_log=lambda msg: log_messages.append(msg),
    )

    # "Line one.\nLine two.\nLine three.\n" → 4 个行：3 个非空 + 1 个尾部空行，共 4 个 TranslationUnit
    # 进度回调：1 次初始化 + 4 次翻译完成 = 5 次
    assert len(progress_calls) == 5

    # 最后一次：current == total == 4
    last = progress_calls[-1]
    assert last[0] == 4  # current
    assert last[1] == 4  # total

    # 日志回调被调用，包含关键状态信息
    assert len(log_messages) > 0
    assert any("读取" in m for m in log_messages)
    assert any("完成" in m for m in log_messages)


def test_on_progress_total_matches_unit_count(tmp_path):
    """on_progress 的 total 参数与实际 TranslationUnit 数量一致。"""
    source = tmp_path / "two.md"
    source.write_text("First line.\nSecond line.\n", encoding="utf-8")

    progress_calls: list[tuple[int, int, int]] = []
    translate_document(
        source,
        MockLLMClient(),
        on_progress=lambda c, t, uid: progress_calls.append((c, t, uid)),
    )

    # "First line.\nSecond line.\n" → 2 个非空行 + 1 个尾部空行，共 3 个 TranslationUnit
    totals = {t for _, t, _ in progress_calls}
    assert totals == {3}


def test_callbacks_are_optional(tmp_path):
    """不传回调时 translate_document 正常运行，不报错。"""
    source = tmp_path / "bare.md"
    source.write_text("Hello.\n", encoding="utf-8")

    target = translate_document(source, MockLLMClient())
    assert target.exists()
    assert "[translated] Hello." in target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 错误处理测试
# ---------------------------------------------------------------------------


class _FailingLLMClient:
    """翻译时抛出异常的 Mock 客户端，用于测试错误处理。"""

    def translate_batch(self, units):
        raise RuntimeError("模拟网络错误")


def test_error_not_raised_to_caller_when_callback_present(tmp_path):
    """LLM 抛出异常时，translate_document 正常抛出（GUI 层面会捕获）。"""
    source = tmp_path / "fail.md"
    source.write_text("Something.\n", encoding="utf-8")

    log_messages: list[str] = []

    try:
        translate_document(
            source,
            _FailingLLMClient(),
            on_log=lambda msg: log_messages.append(msg),
        )
        # 如果没有抛出异常，测试失败
        assert False, "期望 RuntimeError 被抛出"
    except RuntimeError as exc:
        assert "模拟网络错误" in str(exc)


def test_progress_callback_called_before_error(tmp_path):
    """出错前，进度回调和日志回调已被调用（读取、预处理阶段）。"""
    source = tmp_path / "fail2.md"
    source.write_text("Blah.\n", encoding="utf-8")

    progress_calls: list[tuple[int, int, int]] = []
    log_messages: list[str] = []

    try:
        translate_document(
            source,
            _FailingLLMClient(),
            on_progress=lambda c, t, uid: progress_calls.append((c, t, uid)),
            on_log=lambda msg: log_messages.append(msg),
        )
    except RuntimeError:
        pass

    # 翻译前的回调应该已被触发
    assert len(log_messages) >= 2  # "读取" + "预处理"
    assert any("读取" in m for m in log_messages)
    assert any("预处理" in m for m in log_messages)
    # 进度回调应有初始化那次（current=0）
    assert len(progress_calls) >= 1
    assert progress_calls[0][0] == 0  # 初始 current = 0
