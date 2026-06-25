"""LLM 客户端测试（issue #6 切片 5：接入 DeepSeek API 与重试机制）"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from main import LLMClient, TranslationUnit


# ---------------------------------------------------------------------------
# API Key 校验
# ---------------------------------------------------------------------------


def test_empty_api_key_raises_value_error():
    """API Key 为空时抛出 ValueError。"""
    with pytest.raises(ValueError, match="API Key 未配置"):
        LLMClient(api_key="")


def test_whitespace_api_key_raises_value_error():
    """API Key 仅含空白时抛出 ValueError。"""
    with pytest.raises(ValueError, match="API Key 未配置"):
        LLMClient(api_key="   ")


# ---------------------------------------------------------------------------
# 成功调用
# ---------------------------------------------------------------------------


@patch("requests.post")
def test_translate_returns_translated_text(mock_post: MagicMock):
    """配置有效时，调用 DeepSeek API 返回真实中文翻译。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "你好世界"}}]
    }
    mock_post.return_value = mock_resp

    client = LLMClient(api_key="test-key-123")
    unit = TranslationUnit(unit_id=0, original="Hello world")
    result = client.translate(unit)

    assert result.unit_id == 0
    assert result.translated == "你好世界"

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-key-123"


# ---------------------------------------------------------------------------
# 网络失败重试
# ---------------------------------------------------------------------------


@patch("main.time.sleep")
@patch("requests.post")
def test_retry_on_connection_error_then_success(mock_post: MagicMock, mock_sleep: MagicMock):
    """网络连接失败后重试，最终成功。"""
    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.raise_for_status = MagicMock()
    success_resp.json.return_value = {
        "choices": [{"message": {"content": "成功翻译"}}]
    }

    mock_post.side_effect = [requests.ConnectionError("连接失败"), success_resp]

    client = LLMClient(api_key="test-key")
    unit = TranslationUnit(unit_id=0, original="test")
    result = client.translate(unit)

    assert result.translated == "成功翻译"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(1.0)  # 首次退避 1 秒


@patch("main.time.sleep")
@patch("requests.post")
def test_retry_on_timeout_then_success(mock_post: MagicMock, mock_sleep: MagicMock):
    """请求超时后重试，最终成功。"""
    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.raise_for_status = MagicMock()
    success_resp.json.return_value = {
        "choices": [{"message": {"content": "超时重试成功"}}]
    }

    mock_post.side_effect = [requests.Timeout("超时"), success_resp]

    client = LLMClient(api_key="test-key")
    unit = TranslationUnit(unit_id=0, original="test")
    result = client.translate(unit)

    assert result.translated == "超时重试成功"
    assert mock_post.call_count == 2


@patch("main.time.sleep")
@patch("requests.post")
def test_retry_exhausted_raises_runtime_error(mock_post: MagicMock, mock_sleep: MagicMock):
    """重试次数用尽后抛出 RuntimeError。"""
    mock_post.side_effect = requests.ConnectionError("持续失败")

    client = LLMClient(api_key="test-key")
    unit = TranslationUnit(unit_id=0, original="test")

    with pytest.raises(RuntimeError, match="翻译单元 0 失败"):
        client.translate(unit)

    assert mock_post.call_count == 4  # 1 次初始 + 3 次重试
    assert mock_sleep.call_count == 3
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)


# ---------------------------------------------------------------------------
# 429 限流
# ---------------------------------------------------------------------------


@patch("main.time.sleep")
@patch("requests.post")
def test_retry_on_429_rate_limit(mock_post: MagicMock, mock_sleep: MagicMock):
    """HTTP 429 限流触发重试，后续成功。"""
    rate_limit_resp = MagicMock()
    rate_limit_resp.status_code = 429
    rate_limit_resp.raise_for_status = MagicMock()
    rate_limit_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "429", response=rate_limit_resp
    )

    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.raise_for_status = MagicMock()
    success_resp.json.return_value = {
        "choices": [{"message": {"content": "限流后成功"}}]
    }

    mock_post.side_effect = [rate_limit_resp, success_resp]

    client = LLMClient(api_key="test-key")
    unit = TranslationUnit(unit_id=0, original="test")
    result = client.translate(unit)

    assert result.translated == "限流后成功"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(1.0)
