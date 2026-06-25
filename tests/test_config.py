"""配置模块单元测试（issue #3 切片 2）"""

import json
from pathlib import Path
from unittest.mock import patch

from main import Config, _DEFAULT_API_BASE, load_config, save_config


def test_config_default_values():
    """Config 的默认值应正确：空 source_path、空 api_key、默认 api_base。"""
    config = Config()
    assert config.source_path == Path()
    assert config.api_key == ""
    assert config.api_base == _DEFAULT_API_BASE


def test_save_and_load_roundtrip(tmp_path):
    """save_config 后 load_config 应返回相同的 api_key 和 api_base。"""
    config_dir = tmp_path / ".config" / "translate-markdown"
    config_file = config_dir / "config.json"

    original = Config(api_key="sk-test-123", api_base="https://custom.api.com")

    with patch("main.config_path", return_value=config_file):
        save_config(original)
        loaded = load_config()

    assert loaded.api_key == original.api_key
    assert loaded.api_base == original.api_base


def test_load_config_file_not_exist(tmp_path):
    """配置文件不存在时，load_config 应返回默认值。"""
    config_file = tmp_path / "nonexistent" / "config.json"

    with patch("main.config_path", return_value=config_file):
        config = load_config()

    assert config.api_key == ""
    assert config.api_base == _DEFAULT_API_BASE


def test_save_config_creates_parent_dirs(tmp_path):
    """save_config 应自动创建父目录。"""
    config_file = tmp_path / "deep" / "nested" / "config.json"

    with patch("main.config_path", return_value=config_file):
        save_config(Config(api_key="key", api_base="https://example.com"))

    assert config_file.is_file()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["api_key"] == "key"
    assert data["api_base"] == "https://example.com"


def test_save_config_omits_source_path(tmp_path):
    """配置文件不应包含 source_path 字段。"""
    config_file = tmp_path / "config.json"

    with patch("main.config_path", return_value=config_file):
        save_config(Config(api_key="k", api_base="https://a.com"))

    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "source_path" not in data
