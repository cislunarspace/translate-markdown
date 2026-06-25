"""端到端测试：CLI 完整流程（issue #2 切片 1）"""

import subprocess
import textwrap
from pathlib import Path


def test_cli_generates_target_document(tmp_path):
    """运行 main.py 后生成目标文档，mock LLM 翻译结果正确写入。"""
    # Arrange：准备源文档
    source = tmp_path / "hello.md"
    source.write_text(
        textwrap.dedent("""\
            # Introduction

            This is a test paragraph.

            Another line here.
        """),
        encoding="utf-8",
    )

    # Act：运行 CLI
    result = subprocess.run(
        ["python", "main.py", str(source)],
        capture_output=True,
        text=True,
    )

    # Assert：退出码为 0
    assert result.returncode == 0, f"stderr: {result.stderr}"

    # 目标文档存在
    target = tmp_path / "hello_zh.md"
    assert target.exists(), "目标文档未生成"

    # 目标文档内容由 mock LLM 翻译（每行加前缀）
    content = target.read_text(encoding="utf-8")
    assert "[translated] # Introduction" in content
    assert "[translated] This is a test paragraph." in content
    assert "[translated] Another line here." in content


def test_cli_with_nested_path(tmp_path):
    """源文档位于子目录时，目标文档也生成在同一子目录。"""
    nested = tmp_path / "subdir"
    nested.mkdir()
    source = nested / "page.md"
    source.write_text("Hello world.\n", encoding="utf-8")

    result = subprocess.run(
        ["python", "main.py", str(source)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"

    target = nested / "page_zh.md"
    assert target.exists(), "目标文档未在源文档同目录生成"

    content = target.read_text(encoding="utf-8")
    assert "[translated] Hello world." in content


def test_cli_missing_file_exits_with_error(tmp_path):
    """源文档不存在时，CLI 以非零退出码退出并给出提示。"""
    source = tmp_path / "nonexistent.md"

    result = subprocess.run(
        ["python", "main.py", str(source)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_cli_no_arguments_shows_usage():
    """未提供参数时，CLI 显示用法并以非零退出码退出。"""
    result = subprocess.run(
        ["python", "main.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
