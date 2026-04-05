import pytest
from unittest.mock import patch, MagicMock
from llm import call_ollama, OllamaError


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = "error text"
    return resp


@patch("llm.requests.post")
def test_successful_call(mock_post):
    mock_post.return_value = _mock_response(200, {"response": "Анализ готов"})
    result = call_ollama("текст ТЗ", "12345")
    assert result == "Анализ готов"
    mock_post.assert_called_once()


@patch("llm.requests.post")
def test_api_error_raises(mock_post):
    mock_post.return_value = _mock_response(500)
    with pytest.raises(OllamaError, match="API вернул 500"):
        call_ollama("текст", "12345")


@patch("llm.requests.post", side_effect=ConnectionError("refused"))
def test_network_error_raises(mock_post):
    with pytest.raises(OllamaError, match="Сбой сети"):
        call_ollama("текст", "12345")
