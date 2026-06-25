"""端到端测试：CLI 完整流程（issue #2 切片 1）"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def _run_cli(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """在隔离的 HOME 目录下运行 CLI，避免读取用户真实配置中的 API Key。"""
    home_dir = tmp_path / "home"
    home_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    # Path.home() 在 Windows 优先读 USERPROFILE，Unix 优先读 HOME
    env["USERPROFILE"] = str(home_dir)
    env["HOME"] = str(home_dir)
    return subprocess.run(
        [sys.executable, "main.py", *args],
        capture_output=True,
        text=True,
        env=env,
    )


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
    result = _run_cli(tmp_path, [str(source)])

    # Assert：退出码为 0
    assert result.returncode == 0, f"stderr: {result.stderr}"

    # 目标文档存在
    target = tmp_path / "hello_zh.md"
    assert target.exists(), "目标文档未生成"

    # Mock LLM 会在每段原文前加 [translated] 前缀
    content = target.read_text(encoding="utf-8")
    assert "[translated]" in content
    assert "# Introduction" in content


def test_cli_with_nested_path(tmp_path):
    """源文档位于子目录时，目标文档也生成在同一子目录。"""
    nested = tmp_path / "subdir"
    nested.mkdir()
    source = nested / "page.md"
    source.write_text("Hello world.\n", encoding="utf-8")

    result = _run_cli(tmp_path, [str(source)])

    assert result.returncode == 0, f"stderr: {result.stderr}"

    target = nested / "page_zh.md"
    assert target.exists(), "目标文档未在源文档同目录生成"

    content = target.read_text(encoding="utf-8")
    assert "[translated] Hello world." in content


def test_cli_missing_file_exits_with_error(tmp_path):
    """源文档不存在时，CLI 以非零退出码退出并给出提示。"""
    source = tmp_path / "nonexistent.md"

    result = _run_cli(tmp_path, [str(source)])

    assert result.returncode != 0


def test_cli_verbose_outputs_unit_logs(tmp_path):
    """CLI 使用 --verbose 时，应输出每个单元的原文与译文。"""
    source = tmp_path / "verbose.md"
    source.write_text("Hello world.\n", encoding="utf-8")

    result = _run_cli(tmp_path, ["--verbose", "--parallel", "2", str(source)])

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "[单元" in result.stdout
    assert "原文：" in result.stdout
    assert "译文：" in result.stdout


def test_cli_loads_config_from_isolated_home(tmp_path):
    """CLI 从隔离的 HOME 目录读取本地配置并正常完成翻译。"""
    source = tmp_path / "parallel_default.md"
    source.write_text("Hello.\n", encoding="utf-8")

    # 在隔离的 HOME 中写入本地配置
    home_dir = tmp_path / "home"
    config_dir = home_dir / ".config" / "translate-markdown"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(
        '{"api_key": "", "api_base": "https://api.deepseek.com", "parallel_count": 2}',
        encoding="utf-8",
    )

    result = _run_cli(tmp_path, [str(source)])

    assert result.returncode == 0, f"stderr: {result.stderr}"
    target = tmp_path / "parallel_default_zh.md"
    assert target.exists()
    assert "[translated] Hello." in target.read_text(encoding="utf-8")


def test_cli_no_arguments_shows_usage(tmp_path):
    """未提供参数时，CLI 显示用法并以非零退出码退出。"""
    result = _run_cli(tmp_path, [])

    assert result.returncode != 0
