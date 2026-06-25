"""断点续翻测试（issue #7 切片 6：Checkpoint）"""

import json
from pathlib import Path

import pytest

from main import (
    Block,
    TranslationUnit,
    compute_checkpoint_path,
    compute_source_hash,
    load_checkpoint,
    preprocess,
    save_checkpoint,
    translate_document,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

_SOURCE = """\
# Hello

This is a paragraph.

Another paragraph.
"""


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "doc.md"
    source.write_text(_SOURCE, encoding="utf-8")
    return source


# ---------------------------------------------------------------------------
# compute_source_hash
# ---------------------------------------------------------------------------


def test_compute_source_hash_stable():
    """同一文本每次计算的 hash 相同。"""
    h1 = compute_source_hash(_SOURCE)
    h2 = compute_source_hash(_SOURCE)
    assert h1 == h2
    assert len(h1) == 32  # MD5 十六进制长度


def test_compute_source_hash_differs_on_change():
    """文本变更后 hash 不同。"""
    h1 = compute_source_hash(_SOURCE)
    h2 = compute_source_hash(_SOURCE + " extra")
    assert h1 != h2


# ---------------------------------------------------------------------------
# compute_checkpoint_path
# ---------------------------------------------------------------------------


def test_compute_checkpoint_path(tmp_path):
    source = tmp_path / "article.md"
    expected = tmp_path / ".article_zh.checkpoint.json"
    assert compute_checkpoint_path(source) == expected


# ---------------------------------------------------------------------------
# save_checkpoint / load_checkpoint
# ---------------------------------------------------------------------------


def test_save_and_load_checkpoint(tmp_path):
    """保存后再加载，数据一致。"""
    source = _write_source(tmp_path)
    source_hash = compute_source_hash(_SOURCE)
    blocks = [
        Block(block_id=0, original="hello", translated="你好", unit_id=0),
        Block(block_id=1, original="```\ncode\n```", translated=None),
    ]
    completed_ids = [0]
    ckpt_path = compute_checkpoint_path(source)

    save_checkpoint(ckpt_path, source_hash, blocks, completed_ids)

    loaded = load_checkpoint(ckpt_path, source_hash)
    assert loaded is not None
    saved_blocks, saved_ids = loaded
    assert saved_ids == [0]
    assert saved_blocks[0].translated == "你好"
    assert saved_blocks[1].translated is None


def test_load_checkpoint_returns_none_when_missing(tmp_path):
    """checkpoint 文件不存在时返回 None。"""
    source = _write_source(tmp_path)
    ckpt_path = compute_checkpoint_path(source)
    assert load_checkpoint(ckpt_path, "abc") is None


def test_load_checkpoint_returns_none_when_hash_mismatch(tmp_path):
    """source_hash 不匹配时返回 None。"""
    source = _write_source(tmp_path)
    ckpt_path = compute_checkpoint_path(source)
    save_checkpoint(ckpt_path, "old_hash", [], [])
    assert load_checkpoint(ckpt_path, "new_hash") is None


# ---------------------------------------------------------------------------
# translate_document：正常流程（无 checkpoint）
# ---------------------------------------------------------------------------


class _RecordingLLM:
    """记录每次 translate_batch 接收的 units，用 Mock 行为返回。"""

    def __init__(self):
        self.received: list[list[TranslationUnit]] = []

    def translate_batch(self, units):
        self.received.append(list(units))
        return [
            TranslationResult(unit_id=u.unit_id, translated=f"[zh] {u.original}")
            for u in units
        ]


from main import TranslationResult


def test_translate_document_no_checkpoint(tmp_path):
    """无 checkpoint 时正常翻译全部 units。"""
    source = _write_source(tmp_path)
    llm = _RecordingLLM()

    target_path = translate_document(source, llm)

    assert target_path.exists()
    content = target_path.read_text(encoding="utf-8")
    assert "[zh] # Hello" in content
    assert "[zh] This is a paragraph." in content
    assert "[zh] Another paragraph." in content
    # checkpoint 已删除
    ckpt_path = compute_checkpoint_path(source)
    assert not ckpt_path.exists()


# ---------------------------------------------------------------------------
# translate_document：断点续翻
# ---------------------------------------------------------------------------


class _PartialLLM:
    """第一次调用翻译第一个 unit，第二次调用翻译全部。用于模拟中断。"""

    def __init__(self):
        self.call_count = 0
        self.received: list[list[TranslationUnit]] = []

    def translate_batch(self, units):
        self.call_count += 1
        self.received.append(list(units))
        return [
            TranslationResult(unit_id=u.unit_id, translated=f"[zh] {u.original}")
            for u in units
        ]


def test_checkpoint_interrupted_then_resume(tmp_path):
    """第一次只翻译部分 units，手动保存 checkpoint 后继续翻译剩余 units。"""
    source = _write_source(tmp_path)
    source_text = source.read_text(encoding="utf-8")
    source_hash = compute_source_hash(source_text)
    blocks, units, _ = preprocess(source_text)

    # 只翻译第一个 unit，手动保存 checkpoint
    first_unit = units[:1]
    first_results = [
        TranslationResult(unit_id=u.unit_id, translated=f"[zh] {u.original}")
        for u in first_unit
    ]
    completed_ids = [u.unit_id for u in first_unit]

    # 构造部分翻译后的 blocks
    translated_map = {r.unit_id: r.translated for r in first_results}
    partial_blocks = []
    for b in blocks:
        if b.unit_id is not None and b.unit_id in translated_map:
            partial_blocks.append(
                Block(
                    block_id=b.block_id,
                    original=b.original,
                    translated=translated_map[b.unit_id],
                    unit_id=b.unit_id,
                    ip_paths=b.ip_paths,
                )
            )
        else:
            partial_blocks.append(b)

    ckpt_path = compute_checkpoint_path(source)
    save_checkpoint(ckpt_path, source_hash, partial_blocks, completed_ids)

    # 重新运行翻译，应从断点继续
    llm = _PartialLLM()
    target_path = translate_document(source, llm)

    content = target_path.read_text(encoding="utf-8")
    # 第一个 unit 的翻译来自 checkpoint，后续来自 LLM
    assert "[zh] # Hello" in content
    assert "[zh] This is a paragraph." in content
    assert "[zh] Another paragraph." in content
    # LLM 只收到了未完成的 units（第一个 unit 已在 checkpoint 中，不应重复调用）
    all_received_ids = [u.unit_id for batch in llm.received for u in batch]
    assert units[0].unit_id not in all_received_ids
    # checkpoint 已删除
    assert not ckpt_path.exists()


# ---------------------------------------------------------------------------
# translate_document：源文件变更后丢弃旧 checkpoint
# ---------------------------------------------------------------------------


def test_checkpoint_discarded_when_source_changes(tmp_path):
    """源文件变更后，旧 checkpoint 被忽略，从头翻译。"""
    source = _write_source(tmp_path)
    source_text = source.read_text(encoding="utf-8")
    source_hash = compute_source_hash(source_text)
    blocks, units, _ = preprocess(source_text)

    # 用旧 hash 保存一个"错误"的 checkpoint（翻译内容为垃圾数据）
    ckpt_path = compute_checkpoint_path(source)
    garbage_blocks = [
        Block(block_id=0, original="garbage", translated="garbage_translated", unit_id=0),
    ]
    save_checkpoint(ckpt_path, "old_wrong_hash", garbage_blocks, [0])

    # 正常翻译，旧 checkpoint 应被忽略
    llm = _RecordingLLM()
    target_path = translate_document(source, llm)

    content = target_path.read_text(encoding="utf-8")
    # 不应包含旧 checkpoint 的垃圾翻译
    assert "garbage_translated" not in content
    assert "[zh] # Hello" in content
    assert "[zh] This is a paragraph." in content


# ---------------------------------------------------------------------------
# translate_document：checkpoint 文件在翻译完成后被删除
# ---------------------------------------------------------------------------


def test_checkpoint_deleted_after_completion(tmp_path):
    """翻译全部完成后，checkpoint 文件被删除。"""
    source = _write_source(tmp_path)
    llm = _RecordingLLM()

    translate_document(source, llm)

    ckpt_path = compute_checkpoint_path(source)
    assert not ckpt_path.exists()


# ---------------------------------------------------------------------------
# checkpoint JSON 格式可读性
# ---------------------------------------------------------------------------


def test_checkpoint_json_is_pretty_printed(tmp_path):
    """checkpoint JSON 使用 indent=2 格式化。"""
    source = _write_source(tmp_path)
    source_hash = compute_source_hash(_SOURCE)
    blocks = [Block(block_id=0, original="hello", translated="你好", unit_id=0)]
    ckpt_path = compute_checkpoint_path(source)

    save_checkpoint(ckpt_path, source_hash, blocks, [0])

    raw = ckpt_path.read_text(encoding="utf-8")
    # 有缩进表示格式化了
    assert "\n  " in raw
    # 能正常解析
    data = json.loads(raw)
    assert "source_hash" in data
    assert "completed_units" in data
    assert "blocks" in data


# ---------------------------------------------------------------------------
# translate_document：逐 unit 调用 LLM（checkpoint 粒度验证）
# ---------------------------------------------------------------------------


def test_translate_document_calls_llm_per_unit(tmp_path):
    """翻译过程中，每个未完成 unit 单独调用一次 translate_batch。"""
    source = _write_source(tmp_path)
    source_text = source.read_text(encoding="utf-8")
    _, units, _ = preprocess(source_text)

    llm = _RecordingLLM()
    translate_document(source, llm)

    # 每个 unit 各调用一次
    assert len(llm.received) == len(units)
    for i, batch in enumerate(llm.received):
        assert len(batch) == 1
        assert batch[0].unit_id == units[i].unit_id
