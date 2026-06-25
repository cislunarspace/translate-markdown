"""GUI 进度回调与错误处理测试（issue #8 切片 7）"""

import textwrap
from pathlib import Path

import pytest

from main import MockLLMClient, TranslationUnit, TranslationResult, translate_document


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

    def translate(self, unit):
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


def test_translate_document_parallel_count_produces_same_output(tmp_path):
    """parallel_count > 1 时，翻译结果与串行一致。"""
    source = tmp_path / "parallel.md"
    source.write_text(
        textwrap.dedent("""\
            Line one.
            Line two.
            Line three.
        """),
        encoding="utf-8",
    )

    target_serial = translate_document(source, MockLLMClient(), parallel_count=1)
    target_parallel = translate_document(source, MockLLMClient(), parallel_count=2)

    assert target_serial.read_text(encoding="utf-8") == target_parallel.read_text(encoding="utf-8")
    assert "[translated] Line one." in target_parallel.read_text(encoding="utf-8")


class _SlowLLMClient:
    """每个单元睡眠固定时长的 Mock 客户端，用于验证并发确实生效。"""

    def __init__(self, delay: float = 0.05) -> None:
        self._delay = delay

    def translate(self, unit: TranslationUnit) -> TranslationResult:
        import time

        time.sleep(self._delay)
        return TranslationResult(unit_id=unit.unit_id, translated=f"[translated] {unit.original}")


def test_translate_document_parallel_is_faster_than_sequential(tmp_path):
    """parallel_count=2 时，4 个单元的总耗时应明显小于串行。"""
    import time

    source = tmp_path / "parallel_speed.md"
    source.write_text(
        "Line one.\nLine two.\nLine three.\nLine four.\n",
        encoding="utf-8",
    )

    delay = 0.05
    sequential_start = time.perf_counter()
    translate_document(source, _SlowLLMClient(delay), parallel_count=1)
    sequential_elapsed = time.perf_counter() - sequential_start

    parallel_start = time.perf_counter()
    translate_document(source, _SlowLLMClient(delay), parallel_count=2)
    parallel_elapsed = time.perf_counter() - parallel_start

    # 串行 ≈ 4 * delay；并行 ≈ 2 * delay。要求并行明显快于串行（至少快 30%）。
    assert parallel_elapsed < sequential_elapsed * 0.7


class _FailingOnUnitOneLLMClient:
    """仅当 unit_id == 1 时抛异常的 Mock 客户端，用于验证并发失败传播。"""

    def translate(self, unit: TranslationUnit) -> TranslationResult:
        if unit.unit_id == 1:
            raise RuntimeError("模拟单元 1 失败")
        return TranslationResult(unit_id=unit.unit_id, translated=f"[translated] {unit.original}")


def test_parallel_fail_fast_propagates_error(tmp_path):
    """并发模式下，任一单元失败应将异常抛给调用方。"""
    source = tmp_path / "parallel_fail.md"
    source.write_text(
        "Line one.\nLine two.\nLine three.\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="模拟单元 1 失败"):
        translate_document(
            source,
            _FailingOnUnitOneLLMClient(),
            parallel_count=2,
        )


def test_on_unit_translated_callback_receives_unit_and_result(tmp_path):
    """translate_document 应在每个单元完成后调用 on_unit_translated 回调。"""
    source = tmp_path / "unit_log.md"
    source.write_text("Hello world.", encoding="utf-8")

    received: list[tuple[int, str, str]] = []

    translate_document(
        source,
        MockLLMClient(),
        on_unit_translated=lambda unit, result: received.append(
            (unit.unit_id, unit.original, result.translated)
        ),
    )

    assert len(received) == 1
    unit_id, original, translated = received[0]
    assert unit_id == 0
    assert original == "Hello world."
    assert translated == "[translated] Hello world."


def test_format_unit_log_includes_original_and_translated():
    """_format_unit_log 输出应包含单元编号、原文和译文。"""
    from main import _format_unit_log

    unit = TranslationUnit(unit_id=2, original="Hello")
    result = TranslationResult(unit_id=2, translated="你好")

    log = _format_unit_log(unit, result, current=2, total=5)

    assert "[单元 2/5]" in log
    assert "原文：Hello" in log
    assert "译文：你好" in log


def test_format_unit_log_truncates_long_text():
    """原文或译文超过最大长度时应截断并提示总长度。"""
    from main import _format_unit_log

    long_original = "A" * 500
    long_translated = "B" * 400
    unit = TranslationUnit(unit_id=0, original=long_original)
    result = TranslationResult(unit_id=0, translated=long_translated)

    log = _format_unit_log(unit, result, current=1, total=1, max_length=300)

    assert "..." in log
    assert "（共 500 字符）" in log
    assert "（共 400 字符）" in log
    assert len(log) < len(long_original) + len(long_translated)
