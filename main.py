"""translate-markdown — 将英文 Markdown 文档翻译成中文的工具。

单文件脚本，按职责分为四个模块区域：
1. 配置模块
2. LLM 模块
3. 后端模块
4. 前端模块（CLI / GUI）
"""

import argparse
import hashlib
import json
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# 配置模块
# ---------------------------------------------------------------------------

# DeepSeek 默认请求地址
_DEFAULT_API_BASE = "https://api.deepseek.com"


@dataclass(frozen=True)
class Config:
    """运行时配置。

    Attributes
    ----------
    source_path : Path
        源文档路径。
    api_key : str
        大语言模型的 API Key。
    api_base : str
        大语言模型的请求地址。
    parallel_count : int
        同时发起的 LLM 翻译请求数量，默认 3。
    verbose : bool
        CLI 是否输出单元级翻译日志，默认 False。不持久化到本地配置。
    """

    source_path: Path = Path()
    api_key: str = ""
    api_base: str = _DEFAULT_API_BASE
    parallel_count: int = 3
    verbose: bool = False


CONFIG_PATH = Path.home() / ".config" / "translate-markdown" / "config.json"


def load_config() -> Config:
    """从本地 JSON 文件读取配置，文件不存在时返回默认值。"""
    path = CONFIG_PATH
    if not path.is_file():
        return Config()

    data = json.loads(path.read_text(encoding="utf-8"))
    return Config(
        api_key=data.get("api_key", ""),
        api_base=data.get("api_base", _DEFAULT_API_BASE),
        parallel_count=data.get("parallel_count", 3),
    )


def save_config(config: Config) -> None:
    """将配置写入本地 JSON 文件。"""
    path = CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "api_key": config.api_key,
        "api_base": config.api_base,
        "parallel_count": config.parallel_count,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> Config:
    """解析 CLI 参数，返回 Config。

    先解析命令行参数，再从本地配置文件加载 api_key 和 api_base，
    CLI 参数中的 source_path 始终来自命令行。

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
        nargs="?",
        type=Path,
        default=None,
        help="源文档路径",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="启动图形界面",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        help="并发翻译请求数量（覆盖本地配置，1~10）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出每个翻译单元的原文与译文",
    )
    args = parser.parse_args(argv)

    if args.parallel is not None and not (
        _MIN_PARALLEL_COUNT <= args.parallel <= _MAX_PARALLEL_COUNT
    ):
        print(
            f"错误：--parallel 必须在 {_MIN_PARALLEL_COUNT}~{_MAX_PARALLEL_COUNT} 之间",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # 加载本地配置（api_key、api_base、parallel_count）
    file_config = load_config()

    if args.gui:
        return file_config

    if args.source is None:
        print("错误：未指定源文档路径（GUI 模式请使用 --gui）", file=sys.stderr)
        raise SystemExit(1)

    source_path: Path = args.source.resolve()
    if not source_path.is_file():
        print(f"错误：源文档不存在 — {source_path}", file=sys.stderr)
        raise SystemExit(1)

    return Config(
        source_path=source_path,
        api_key=file_config.api_key,
        api_base=file_config.api_base,
        parallel_count=args.parallel if args.parallel is not None else file_config.parallel_count,
        verbose=args.verbose,
    )


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

    def translate(self, unit: TranslationUnit) -> TranslationResult:
        """将原文加上固定前缀返回；空内容保持原样。"""
        if not unit.original.strip():
            return TranslationResult(unit_id=unit.unit_id, translated=unit.original)
        return TranslationResult(unit_id=unit.unit_id, translated=f"[translated] {unit.original}")


# 重试参数
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # 秒

# 并发数量限制
_MIN_PARALLEL_COUNT = 1
_MAX_PARALLEL_COUNT = 10


class LLMClient:
    """接入 DeepSeek API 的真实 LLM 客户端。

    使用 OpenAI 兼容格式调用 DeepSeek chat completions 接口。
    内置指数退避重试：网络异常和 HTTP 429 会触发重试，最多 3 次。

    Parameters
    ----------
    api_key : str
        DeepSeek API Key，不能为空。
    api_base : str
        API 请求地址。
    """

    def __init__(self, api_key: str, api_base: str = _DEFAULT_API_BASE) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("API Key 未配置，请先设置有效的 API Key")
        self._api_key = api_key
        self._api_base = api_base

    def _translate_single(self, unit: TranslationUnit) -> TranslationResult:
        """调用 DeepSeek API 翻译单个单元。"""
        import requests as _requests

        url = f"{self._api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional translator translating a Markdown document from English to Chinese. "
                        "Translate the content inside the <source> tags into Chinese. "
                        "You must follow these rules:\n"
                        "1. Output ONLY the translation. Do not add explanations, preambles, formatting notes, or meta-commentary.\n"
                        "2. Preserve Markdown formatting, including headings, lists, code blocks, math formulas, and placeholders.\n"
                        "3. Keep URLs, code, math formulas, email addresses, version numbers, and proper nouns unchanged.\n"
                        "4. Do not echo the user's request, ask for clarification, or include the <source> tags in your output."
                    ),
                },
                {
                    "role": "user",
                    "content": f"<source>\n{unit.original}\n</source>",
                },
            ],
        }

        last_exc: Exception | None = None
        backoff = _INITIAL_BACKOFF

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = _requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 429:
                    raise _requests.exceptions.HTTPError(
                        f"HTTP 429: 限流",
                        response=resp,
                    )
                resp.raise_for_status()
                data = resp.json()
                content: str = data["choices"][0]["message"]["content"]
                return TranslationResult(unit_id=unit.unit_id, translated=content)
            except (_requests.ConnectionError, _requests.Timeout, _requests.exceptions.HTTPError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2

        # 重试用尽，抛出最终异常
        raise RuntimeError(
            f"翻译单元 {unit.unit_id} 失败，已重试 {_MAX_RETRIES} 次"
        ) from last_exc

    def translate(self, unit: TranslationUnit) -> TranslationResult:
        """翻译单个单元。空内容直接返回原文，避免无意义的 API 调用。"""
        if not unit.original.strip():
            return TranslationResult(unit_id=unit.unit_id, translated=unit.original)
        return self._translate_single(unit)


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
        原始文本（单行或多行）。
    translated : str | None
        翻译结果，保护块为 None 表示原样保留。
    unit_id : int | None
        对应的 TranslationUnit id，保护块为 None。
    ip_paths : list[str] | None
        该块中图片占位符 {{IP_N}} 对应的原始路径列表。
    """

    block_id: int
    original: str
    translated: str | None = None
    unit_id: int | None = None
    ip_paths: list[str] | None = None


def _extract_inline_code(text: str) -> tuple[str, list[str]]:
    """将行内代码替换为占位符，返回替换后的文本和原始代码列表。

    占位符格式：``{{IC_0}}``、``{{IC_1}}``……
    """
    pattern = re.compile(r"`([^`]+?)`")
    codes: list[str] = []

    def _replace(m: re.Match[str]) -> str:
        idx = len(codes)
        codes.append(m.group(1))
        return f"{{{{IC_{idx}}}}}"

    replaced = pattern.sub(_replace, text)
    return replaced, codes


def _protect_image_paths(text: str) -> tuple[str, list[str]]:
    """将图片路径替换为占位符，返回替换后的文本和原始路径列表。

    匹配 ![alt text](path) 格式，路径部分替换为占位符 ``{{IP_N}}``，
    alt 文本保留在原位供翻译。

    占位符格式：``{{IP_0}}``、``{{IP_1}}``……
    """
    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    paths: list[str] = []

    def _replace(m: re.Match[str]) -> str:
        idx = len(paths)
        paths.append(m.group(2))
        return f"![{m.group(1)}]({{{{IP_{idx}}}}})"

    replaced = pattern.sub(_replace, text)
    return replaced, paths


def preprocess(source_text: str) -> tuple[list[Block], list[TranslationUnit], dict[int, list[str]]]:
    """将源文档文本按物理行拆分为 Block 和 TranslationUnit。

    使用状态机按"代码块 → 行间公式 → 表格 → 行内元素"的顺序识别：
    - fenced code block（``` 或 ~~~ 开头）整体作为保护块
    - LaTeX 行间公式（被 $$ 包裹）整体作为保护块
    - 连续含 | 的行（Markdown 表格）整体作为一个 TranslationUnit
    - 行内代码替换为占位符 ``{{IC_N}}``
    - 图片路径替换为占位符 ``{{IP_N}}``（alt 文本可译）

    Returns
    -------
    blocks : list[Block]
        所有块列表（保护块的 translated 字段为 None）。
    units : list[TranslationUnit]
        可译块对应的翻译单元列表。
    ic_map : dict[int, list[str]]
        TranslationUnit unit_id 到行内代码原始文本列表的映射。
    """
    lines = source_text.split("\n")
    blocks: list[Block] = []
    units: list[TranslationUnit] = []
    ic_map: dict[int, list[str]] = {}
    unit_id = 0
    block_id = 0

    # 状态机状态
    in_code_block = False
    in_table = False
    in_display_math = False
    fence_marker: str | None = None  # 当前代码块的围栏标记（``` 或 ~~~）

    # fence 行正则：3 个以上 ` 或 ~ 开头，后面可跟 info string
    fence_re = re.compile(r"^([`~]{3,})(.*)$")

    # 表格行判定：行中含 |，且不是纯空白
    table_row_re = re.compile(r"^\s*\|.+\|\s*$")

    # 表格分隔行判定：|---|---| 或 | --- | --- |
    table_sep_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")

    # 收集中的表格行
    table_lines: list[str] = []

    # 收集中的行间公式行
    display_math_lines: list[str] = []

    def _flush_table() -> None:
        """将收集中的表格行合并为一个 TranslationUnit。"""
        nonlocal unit_id, block_id
        if not table_lines:
            return
        # 将所有表格行拼接为多行文本，作为一个 TranslationUnit
        table_text = "\n".join(table_lines)
        # 表格整体做行内代码替换（表格中可能有行内代码）
        replaced, codes = _extract_inline_code(table_text)
        block = Block(block_id=block_id, original=table_text, unit_id=unit_id)
        blocks.append(block)
        block_id += 1

        unit = TranslationUnit(unit_id=unit_id, original=replaced)
        units.append(unit)
        if codes:
            ic_map[unit_id] = codes
        unit_id += 1
        table_lines.clear()

    def _flush_display_math() -> None:
        """将收集中的行间公式行合并为一个保护块。"""
        nonlocal block_id
        if not display_math_lines:
            return
        block = Block(
            block_id=block_id,
            original="\n".join(display_math_lines),
        )
        blocks.append(block)
        block_id += 1
        display_math_lines.clear()

    for line in lines:
        stripped = line.strip()

        if in_code_block:
            code_lines.append(line)
            # 检测结束 fence：与开始 fence 同一字符，至少同等长度
            if end_pattern.match(stripped):
                # 代码块结束：合并为一个保护块
                block = Block(block_id=block_id, original="\n".join(code_lines))
                blocks.append(block)
                block_id += 1
                in_code_block = False
                fence_marker = None
            continue

        if in_display_math:
            display_math_lines.append(line)
            if stripped == "$$":
                _flush_display_math()
                in_display_math = False
            continue

        m = fence_re.match(stripped)
        # 只有仅含同种字符的 fence 才算开始（info string 允许）
        if m and all(c == m.group(1)[0] for c in m.group(1)):
            # 进入代码块：先结束已开始的表格
            if in_table:
                _flush_table()
                in_table = False
            # fence 行本身不作为独立 Block，与代码内容合并
            fence_marker = m.group(1)[0]  # 取第一个字符（` 或 ~）
            end_pattern = re.compile(rf"^{re.escape(fence_marker)}{{3,}}\s*$")
            in_code_block = True
            code_lines: list[str] = [line]
            continue

        # 行间公式：独立的 $$ 行开始/结束
        if stripped == "$$":
            # 结束已开始的表格
            if in_table:
                _flush_table()
                in_table = False
            in_display_math = True
            display_math_lines.append(line)
            continue

        # 表格识别：连续含 | 的行整体作为一个 TranslationUnit
        if table_row_re.match(stripped) or table_sep_re.match(stripped):
            if not in_table:
                in_table = True
            table_lines.append(line)
            continue

        # 遇到非表格行，先结束已开始的表格
        if in_table:
            _flush_table()
            in_table = False

        # 空行或纯空白行不生成 TranslationUnit，仅保留为块
        if stripped == "":
            blocks.append(Block(block_id=block_id, original=line, unit_id=None))
            block_id += 1
            continue

        # 普通行：图片路径保护 + 行内代码替换为占位符
        protected, ip_paths = _protect_image_paths(line)
        replaced, codes = _extract_inline_code(protected)
        block = Block(
            block_id=block_id,
            original=line,
            unit_id=unit_id,
            ip_paths=ip_paths if ip_paths else None,
        )
        blocks.append(block)
        block_id += 1

        unit = TranslationUnit(unit_id=unit_id, original=replaced)
        units.append(unit)
        if codes:
            ic_map[unit_id] = codes
        unit_id += 1

    # 文档末尾处理
    if in_table:
        _flush_table()
    # 如果文档末尾有未关闭的代码块，按保护块处理
    if in_code_block:
        block = Block(block_id=block_id, original="\n".join(code_lines))
        blocks.append(block)
    # 如果文档末尾有未关闭的公式块，按保护块处理
    if in_display_math:
        _flush_display_math()

    return blocks, units, ic_map


def merge_results(
    blocks: list[Block],
    results: list[TranslationResult],
    ic_map: dict[int, list[str]] | None = None,
) -> str:
    """将翻译结果回填到块列表，合并为目标文档文本。

    对翻译结果中的行内代码占位符 ``{{IC_N}}``，回填为原始行内代码文本。
    对翻译结果中的图片路径占位符 ``{{IP_N}}``，回填为原始图片路径。
    """
    if ic_map is None:
        ic_map = {}

    result_map = {r.unit_id: r.translated for r in results}
    ic_pattern = re.compile(r"\{\{IC_(\d+)\}\}")
    ip_pattern = re.compile(r"\{\{IP_(\d+)\}\}")
    output_lines: list[str] = []

    for block in blocks:
        uid = block.unit_id
        translated = result_map.get(uid) if uid is not None else None
        if translated is not None:
            # 回填图片路径占位符
            if block.ip_paths:
                paths = block.ip_paths
                def _restore_ip(m: re.Match[str], _paths=paths) -> str:
                    idx = int(m.group(1))
                    return _paths[idx] if idx < len(_paths) else m.group(0)
                translated = ip_pattern.sub(_restore_ip, translated)

            # 回填行内代码占位符
            codes = ic_map.get(uid, [])
            def _restore_ic(m: re.Match[str], _codes=codes) -> str:
                idx = int(m.group(1))
                return f"`{_codes[idx]}`" if idx < len(_codes) else m.group(0)

            restored = ic_pattern.sub(_restore_ic, translated)
            output_lines.append(restored)
        else:
            # 保护块：多行时逐行输出
            output_lines.extend(block.original.split("\n"))

    return "\n".join(output_lines)


def compute_source_hash(source_text: str) -> str:
    """计算源文档文本的 MD5 哈希。"""
    return hashlib.md5(source_text.encode("utf-8")).hexdigest()


def compute_checkpoint_path(source_path: Path) -> Path:
    """返回 checkpoint 文件路径：与目标文档同目录，文件名 .{stem}_zh.checkpoint.json。"""
    return source_path.parent / f".{source_path.stem}_zh.checkpoint.json"


def _truncate_for_log(text: str, max_length: int) -> str:
    """如 text 超过 max_length，则截断并在末尾附加总长度提示。"""
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}...（共 {len(text)} 字符）"


def _format_unit_log(
    unit: TranslationUnit,
    result: TranslationResult,
    current: int | None = None,
    total: int | None = None,
    max_length: int = 300,
) -> str:
    """把一个翻译单元格式化为日志字符串。"""
    original = _truncate_for_log(unit.original, max_length)
    translated = _truncate_for_log(result.translated, max_length)
    if current is not None and total is not None:
        header = f"[单元 {current}/{total}]"
    else:
        header = f"[单元 {unit.unit_id}]"
    return f"{header}\n原文：{original}\n译文：{translated}"


def save_checkpoint(
    path: Path,
    source_hash: str,
    blocks: list[Block],
    completed_ids: list[int],
) -> None:
    """保存 checkpoint JSON，包含 source_hash、已完成 unit_id 列表和完整块列表。"""
    data = {
        "source_hash": source_hash,
        "completed_units": sorted(completed_ids),
        "blocks": [
            {
                "block_id": b.block_id,
                "original": b.original,
                "translated": b.translated,
                "unit_id": b.unit_id,
            }
            for b in blocks
        ],
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_checkpoint(path: Path, source_hash: str) -> tuple[list[Block], list[int]] | None:
    """加载 checkpoint；文件不存在或 source_hash 不匹配时返回 None。"""
    if not path.is_file():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source_hash") != source_hash:
        return None

    completed_ids: list[int] = data.get("completed_units", [])
    blocks = [
        Block(
            block_id=b["block_id"],
            original=b["original"],
            translated=b.get("translated"),
            unit_id=b.get("unit_id"),
        )
        for b in data.get("blocks", [])
    ]
    return blocks, completed_ids



def translate_document(
    source_path: Path,
    llm,  # duck-typed: needs .translate(unit) -> TranslationResult
    on_progress: Callable[[int, int, int], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    on_unit_translated: Callable[[TranslationUnit, TranslationResult], None] | None = None,
    parallel_count: int = 1,
) -> Path:
    """执行完整翻译流程，返回目标文档路径。

    主流程：读取源文档并计算 MD5 → 预处理 → 检查 checkpoint →
    翻译循环（按 parallel_count 并发调用 LLM，回填结果，更新 checkpoint）→
    合并输出 → 写入目标文档 → 删除 checkpoint。

    Parameters
    ----------
    on_progress : callable | None
        进度回调，签名为 (current, total, unit_id)，每完成一个 unit 调用一次。
    on_log : callable | None
        日志回调，签名为 (message)，用于输出运行状态信息。
    on_unit_translated : callable | None
        单元完成回调，签名为 (unit, result)，用于展示原文与译文。
    parallel_count : int
        并发翻译请求数量，默认 1（串行）。
    """

    def _log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)

    # 1. 读取源文档并计算 hash
    _log("正在读取源文档…")
    source_text = source_path.read_text(encoding="utf-8")
    source_hash = compute_source_hash(source_text)

    # 2. 预处理
    _log("正在预处理…")
    blocks, units, ic_map = preprocess(source_text)

    # 3. 检查 checkpoint
    ckpt_path = compute_checkpoint_path(source_path)
    ckpt = load_checkpoint(ckpt_path, source_hash)

    completed_ids: set[int] = set()
    translated_map: dict[int, str] = {}

    if ckpt is not None:
        saved_blocks, saved_completed = ckpt
        completed_ids = set(saved_completed)
        # 恢复已有翻译结果
        for b in saved_blocks:
            if b.unit_id is not None and b.translated is not None:
                translated_map[b.unit_id] = b.translated
        _log(f"已从进度缓存恢复 {len(completed_ids)} 个单元")

    # 4. 翻译未完成的 units
    pending_units = [u for u in units if u.unit_id not in completed_ids]
    total = len(units)
    done_count = len(completed_ids)

    if on_progress is not None:
        on_progress(done_count, total, -1)

    parallel_count = max(_MIN_PARALLEL_COUNT, min(parallel_count, _MAX_PARALLEL_COUNT))

    def _handle_result(result: TranslationResult, unit: TranslationUnit) -> None:
        """把一个翻译结果回填到内存与 checkpoint，并触发进度回调。"""
        nonlocal done_count
        translated_map[result.unit_id] = result.translated
        completed_ids.add(result.unit_id)
        done_count = len(completed_ids)
        if on_unit_translated is not None:
            on_unit_translated(unit, result)
        # 为 checkpoint 构造更新后的 blocks（回填新翻译）
        updated_blocks: list[Block] = []
        for b in blocks:
            if b.unit_id is not None and b.unit_id in translated_map:
                updated_blocks.append(
                    Block(
                        block_id=b.block_id,
                        original=b.original,
                        translated=translated_map[b.unit_id],
                        unit_id=b.unit_id,
                        ip_paths=b.ip_paths,
                    )
                )
            else:
                updated_blocks.append(b)
        save_checkpoint(
            ckpt_path,
            source_hash,
            updated_blocks,
            sorted(completed_ids),
        )
        if on_progress is not None:
            on_progress(done_count, total, result.unit_id)

    if pending_units:
        _log(f"共 {total} 个单元，待翻译 {len(pending_units)} 个")
        if parallel_count > 1:
            _log(f"并发数量：{parallel_count}")

        if parallel_count == 1:
            for unit in pending_units:
                _log(f"正在翻译单元 {unit.unit_id}（第 {done_count + 1}/{total}）…")
                result = llm.translate(unit)
                _handle_result(result, unit)
        else:
            with ThreadPoolExecutor(max_workers=parallel_count) as executor:
                future_to_unit = {
                    executor.submit(llm.translate, unit): unit
                    for unit in pending_units
                }
                try:
                    for future in as_completed(future_to_unit):
                        result = future.result()
                        _handle_result(result, future_to_unit[future])
                except Exception:
                    for f in future_to_unit:
                        f.cancel()
                    raise
    else:
        _log("所有单元已完成（来自进度缓存）")

    # 5. 合并输出
    _log("正在合并输出…")
    all_results = [
        TranslationResult(unit_id=uid, translated=txt)
        for uid, txt in translated_map.items()
    ]
    target_text = merge_results(blocks, all_results, ic_map)

    # 6. 写入目标文档
    target_path = source_path.parent / f"{source_path.stem}_zh.md"
    target_path.write_text(target_text, encoding="utf-8")

    # 7. 删除 checkpoint
    if ckpt_path.is_file():
        ckpt_path.unlink()

    _log(f"翻译完成：{target_path}")
    return target_path


# ---------------------------------------------------------------------------
# 前端模块 — CLI
# ---------------------------------------------------------------------------


def run_cli(config: Config) -> None:
    """CLI 入口。"""
    if config.api_key:
        llm = LLMClient(api_key=config.api_key, api_base=config.api_base)
    else:
        llm = MockLLMClient()

    unit_log_handler = None
    if config.verbose:
        def _print_unit_log(unit: TranslationUnit, result: TranslationResult) -> None:
            print(_format_unit_log(unit, result))
        unit_log_handler = _print_unit_log

    target_path = translate_document(
        config.source_path,
        llm,
        on_unit_translated=unit_log_handler,
        parallel_count=config.parallel_count,
    )
    print(f"翻译完成：{target_path}")


# ---------------------------------------------------------------------------
# 前端模块 — GUI
# ---------------------------------------------------------------------------


def run_gui() -> None:
    """GUI 入口：PyQt6 主窗口，含实时进度与错误展示。"""
    from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
    from PyQt6.QtWidgets import (
        QApplication,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    class _TranslateWorker(QThread):
        """后台翻译线程，通过信号将进度和日志传递到主线程。"""

        progress = pyqtSignal(int, int, int)  # (current, total, unit_id)
        log = pyqtSignal(str)
        finished_ok = pyqtSignal(str)  # 目标文档路径
        error = pyqtSignal(str)  # 错误信息

        def __init__(
            self,
            source_path: Path,
            api_key: str,
            api_base: str,
            parallel_count: int,
            parent=None,
        ) -> None:
            super().__init__(parent)
            self._source_path = source_path
            self._api_key = api_key
            self._api_base = api_base
            self._parallel_count = parallel_count

        def run(self) -> None:
            try:
                llm = LLMClient(
                    api_key=self._api_key, api_base=self._api_base
                )
                total_units = 0

                def _on_progress(current: int, total: int, unit_id: int) -> None:
                    nonlocal total_units
                    if unit_id == -1:
                        total_units = total
                    self.progress.emit(current, total, unit_id)

                def _on_unit_translated(
                    unit: TranslationUnit, result: TranslationResult
                ) -> None:
                    self.log.emit(
                        _format_unit_log(
                            unit,
                            result,
                            current=unit.unit_id + 1,
                            total=total_units,
                        )
                    )

                target = translate_document(
                    self._source_path,
                    llm,
                    on_progress=_on_progress,
                    on_log=lambda msg: self.log.emit(msg),
                    on_unit_translated=_on_unit_translated,
                    parallel_count=self._parallel_count,
                )
                self.finished_ok.emit(str(target))
            except Exception as exc:
                tb = traceback.format_exc()
                self.error.emit(f"{exc}\n{tb}")

    config = load_config()

    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("translate-markdown")
    window.setMinimumSize(600, 400)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout(central)

    # 文件选择行
    file_layout = QHBoxLayout()
    file_label = QLabel("源文档：")
    file_path_edit = QLineEdit()
    file_path_edit.setReadOnly(True)
    file_btn = QPushButton("选择文件…")
    file_layout.addWidget(file_label)
    file_layout.addWidget(file_path_edit)
    file_layout.addWidget(file_btn)
    layout.addLayout(file_layout)

    # API Key 输入行
    key_layout = QHBoxLayout()
    key_label = QLabel("API Key：")
    key_edit = QLineEdit()
    key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    key_edit.setText(config.api_key)
    key_layout.addWidget(key_label)
    key_layout.addWidget(key_edit)
    layout.addLayout(key_layout)

    # 请求地址输入行
    base_layout = QHBoxLayout()
    base_label = QLabel("请求地址：")
    base_edit = QLineEdit()
    base_edit.setText(config.api_base)
    base_layout.addWidget(base_label)
    base_layout.addWidget(base_edit)
    layout.addLayout(base_layout)

    # 并行数量输入行
    parallel_layout = QHBoxLayout()
    parallel_label = QLabel("并行数量：")
    parallel_spin = QSpinBox()
    parallel_spin.setRange(_MIN_PARALLEL_COUNT, _MAX_PARALLEL_COUNT)
    parallel_spin.setValue(config.parallel_count)
    parallel_layout.addWidget(parallel_label)
    parallel_layout.addWidget(parallel_spin)
    layout.addLayout(parallel_layout)

    # 保存配置按钮 + 开始翻译按钮
    btn_layout = QHBoxLayout()
    save_btn = QPushButton("保存配置")
    start_btn = QPushButton("开始翻译")
    btn_layout.addWidget(save_btn)
    btn_layout.addWidget(start_btn)
    layout.addLayout(btn_layout)

    # 进度条
    progress_bar = QProgressBar()
    progress_bar.setValue(0)
    progress_bar.setFormat("%v / %m")
    layout.addWidget(progress_bar)

    # 日志文本框
    log_text = QTextEdit()
    log_text.setReadOnly(True)
    layout.addWidget(log_text)

    # 信号连接
    _worker: _TranslateWorker | None = None  # 防止 GC 回收

    def on_select_file() -> None:
        path, _ = QFileDialog.getOpenFileName(
            window, "选择源文档", "", "Markdown 文件 (*.md);;所有文件 (*)"
        )
        if path:
            file_path_edit.setText(path)

    def on_save_config() -> None:
        new_config = Config(
            api_key=key_edit.text(),
            api_base=base_edit.text(),
            parallel_count=parallel_spin.value(),
        )
        save_config(new_config)

    def on_start_translate() -> None:
        nonlocal _worker
        # 校验输入
        source_text = file_path_edit.text().strip()
        if not source_text:
            log_text.append("错误：请选择源文档。")
            return
        source = Path(source_text)
        if not source.is_file():
            log_text.append(f"错误：源文档不存在 — {source}")
            return
        api_key = key_edit.text().strip()
        if not api_key:
            log_text.append("错误：请填写 API Key。")
            return

        # 禁用按钮，重置 UI
        start_btn.setEnabled(False)
        log_text.clear()
        progress_bar.setValue(0)

        _worker = _TranslateWorker(
            source_path=source,
            api_key=api_key,
            api_base=base_edit.text().strip(),
            parallel_count=parallel_spin.value(),
            parent=window,
        )
        _worker.progress.connect(_on_progress)
        _worker.log.connect(_on_log)
        _worker.finished_ok.connect(_on_finished)
        _worker.error.connect(_on_error)
        _worker.start()

    @pyqtSlot(int, int, int)
    def _on_progress(current: int, total: int, unit_id: int) -> None:
        progress_bar.setMaximum(total)
        progress_bar.setValue(current)

    @pyqtSlot(str)
    def _on_log(message: str) -> None:
        log_text.append(message)

    @pyqtSlot(str)
    def _on_finished(target_path: str) -> None:
        start_btn.setEnabled(True)
        log_text.append(f"目标文档已生成：{target_path}")

    @pyqtSlot(str)
    def _on_error(error_msg: str) -> None:
        start_btn.setEnabled(True)
        log_text.append(f"翻译出错：{error_msg}")

    file_btn.clicked.connect(on_select_file)
    save_btn.clicked.connect(on_save_config)
    start_btn.clicked.connect(on_start_translate)

    window.show()
    app.exec()


def main() -> None:
    config = parse_args()
    if config.source_path == Path():
        # GUI 模式：parse_args 已处理 --gui
        run_gui()
    else:
        run_cli(config)


if __name__ == "__main__":
    main()
