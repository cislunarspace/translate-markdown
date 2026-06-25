"""translate-markdown — 将英文 Markdown 翻译成中文的工具。

单文件脚本，按职责分为四个模块区域：
1. 配置模块
2. LLM 模块
3. 后端模块
4. 前端模块（CLI / GUI）
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# 配置模块
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """运行时配置。"""

    source_path: Path


def parse_args(argv: list[str] | None = None) -> Config:
    """解析 CLI 参数，返回 Config。

    Parameters
    ----------
    argv : list[str] | None
        命令行参数，None 表示使用 sys.argv[1:]。
    """
    parser = argparse.ArgumentParser(
        description="将英文 Markdown 文档翻译成中文",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="源文档路径",
    )
    args = parser.parse_args(argv)

    source_path: Path = args.source.resolve()
    if not source_path.is_file():
        print(f"错误：源文档不存在 — {source_path}", file=sys.stderr)
        raise SystemExit(1)

    return Config(source_path=source_path)


# ---------------------------------------------------------------------------
# LLM 模块
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranslationUnit:
    """发送给 LLM 的最小翻译单元。"""

    unit_id: int
    original: str


@dataclass(frozen=True)
class TranslationResult:
    """LLM 返回的翻译结果。"""

    unit_id: int
    translated: str


class MockLLMClient:
    """Mock LLM 客户端，用于切片 1 的端到端打通。"""

    def translate_batch(self, units: list[TranslationUnit]) -> list[TranslationResult]:
        """将每行英文加上固定前缀返回。"""
        return [
            TranslationResult(unit_id=u.unit_id, translated=f"[translated] {u.original}")
            for u in units
        ]


# ---------------------------------------------------------------------------
# 后端模块
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """保护块或待译块，是后处理合并的基本单元。

    Attributes
    ----------
    block_id : int
        块的顺序编号。
    original : str
        原始文本（单行）。
    translated : str | None
        翻译结果，保护块为 None 表示原样保留。
    """

    block_id: int
    original: str
    translated: str | None = None


def preprocess(source_text: str) -> tuple[list[Block], list[TranslationUnit]]:
    """将源文档文本按物理行拆分为 Block 和 TranslationUnit。

    切片 1 不识别保护块，所有行均视为可译块。

    Returns
    -------
    blocks : list[Block]
        所有块列表（待翻译，translated 字段为 None）。
    units : list[TranslationUnit]
        对应的翻译单元列表。
    """
    lines = source_text.split("\n")
    blocks: list[Block] = []
    units: list[TranslationUnit] = []
    unit_id = 0

    for i, line in enumerate(lines):
        block = Block(block_id=i, original=line)
        blocks.append(block)

        # 空行也发送给 LLM，保持行数对齐
        unit = TranslationUnit(unit_id=unit_id, original=line)
        units.append(unit)
        unit_id += 1

    return blocks, units


def merge_results(
    blocks: list[Block],
    results: list[TranslationResult],
) -> str:
    """将翻译结果回填到块列表，合并为目标文档文本。"""
    result_map = {r.unit_id: r.translated for r in results}
    output_lines: list[str] = []

    for i, block in enumerate(blocks):
        translated = result_map.get(i)
        if translated is not None:
            output_lines.append(translated)
        else:
            output_lines.append(block.original)

    return "\n".join(output_lines)


def compute_target_path(source_path: Path) -> Path:
    """计算目标文档路径：{stem}_zh.md，与源文档同目录。"""
    return source_path.parent / f"{source_path.stem}_zh.md"


def translate_document(source_path: Path, llm: MockLLMClient) -> Path:
    """执行完整翻译流程，返回目标文档路径。

    主流程：读取源文档 → 预处理 → 调用 LLM → 合并输出 → 写入目标文档。
    """
    # 1. 读取源文档
    source_text = source_path.read_text(encoding="utf-8")

    # 2. 预处理
    blocks, units = preprocess(source_text)

    # 3. 调用 LLM
    results = llm.translate_batch(units)

    # 4. 合并输出
    target_text = merge_results(blocks, results)

    # 5. 写入目标文档
    target_path = compute_target_path(source_path)
    target_path.write_text(target_text, encoding="utf-8")

    return target_path


# ---------------------------------------------------------------------------
# 前端模块 — CLI
# ---------------------------------------------------------------------------


def run_cli(argv: list[str] | None = None) -> None:
    """CLI 入口。"""
    config = parse_args(argv)
    llm = MockLLMClient()
    target_path = translate_document(config.source_path, llm)
    print(f"翻译完成：{target_path}")


def main() -> None:
    run_cli()


if __name__ == "__main__":
    main()
