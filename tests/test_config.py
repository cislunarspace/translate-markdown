"""配置模块单元测试（issue #3 切片 2）"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from main import Config, _DEFAULT_API_BASE, load_config, parse_args, save_config


def test_config_default_values():
    """Config 的默认值应正确：空 source_path、空 api_key、默认 api_base、默认并行数量。"""
    config = Config()
    assert config.source_path == Path()
    assert config.api_key == ""
    assert config.api_base == _DEFAULT_API_BASE
    assert config.parallel_count == 3


def test_save_and_load_roundtrip(tmp_path):
    """save_config 后 load_config 应返回相同的 api_key、api_base 和 parallel_count。"""
    config_dir = tmp_path / ".config" / "translate-markdown"
    config_file = config_dir / "config.json"

    original = Config(
        api_key="sk-test-123",
        api_base="https://custom.api.com",
        parallel_count=5,
    )

    with patch("main.CONFIG_PATH", config_file):
        save_config(original)
        loaded = load_config()

    assert loaded.api_key == original.api_key
    assert loaded.api_base == original.api_base
    assert loaded.parallel_count == original.parallel_count


def test_load_config_file_not_exist(tmp_path):
    """配置文件不存在时，load_config 应返回默认值。"""
    config_file = tmp_path / "nonexistent" / "config.json"

    with patch("main.CONFIG_PATH", config_file):
        config = load_config()

    assert config.api_key == ""
    assert config.api_base == _DEFAULT_API_BASE


def test_save_config_creates_parent_dirs(tmp_path):
    """save_config 应自动创建父目录。"""
    config_file = tmp_path / "deep" / "nested" / "config.json"

    with patch("main.CONFIG_PATH", config_file):
        save_config(Config(api_key="key", api_base="https://example.com"))

    assert config_file.is_file()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["api_key"] == "key"
    assert data["api_base"] == "https://example.com"


def test_save_config_omits_source_path(tmp_path):
    """配置文件不应包含 source_path 字段。"""
    config_file = tmp_path / "config.json"

    with patch("main.CONFIG_PATH", config_file):
        save_config(Config(api_key="k", api_base="https://a.com"))

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "source_path" not in data


def test_parse_args_parallel_override(tmp_path):
    """CLI 的 --parallel 参数应覆盖本地配置的默认值。"""
    source = tmp_path / "doc.md"
    source.write_text("Hello.\n", encoding="utf-8")

    config = parse_args(["--parallel", "7", str(source)])
    assert config.parallel_count == 7


def test_parse_args_parallel_falls_back_to_file_config(tmp_path):
    """CLI 未指定 --parallel 时，应回退到本地配置中的 parallel_count。"""
    source = tmp_path / "doc.md"
    source.write_text("Hello.\n", encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text('{"parallel_count": 5}', encoding="utf-8")

    with patch("main.CONFIG_PATH", config_file):
        config = parse_args([str(source)])

    assert config.parallel_count == 5


def test_parse_args_rejects_parallel_out_of_range(tmp_path):
    """CLI 的 --parallel 超出 1~10 范围时应以非零退出码退出。"""
    source = tmp_path / "doc.md"
    source.write_text("Hello.\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        parse_args(["--parallel", "100", str(source)])
