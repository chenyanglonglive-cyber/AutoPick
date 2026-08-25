from __future__ import annotations

import httpx
import pytest

from backend.autopick.qwen import QwenEmbeddingClient, QwenError


class MockResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code
        self.text = "Error detail"

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://mock.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("HTTP Error", request=request, response=response)


def test_qwen_demo_vector():
    client = QwenEmbeddingClient(api_key=None, model="test-model", dimension=1024, demo=True)
    res = client.embed_text("test query")
    assert res.vector.shape == (1024,)
    assert res.input_tokens == 0


def test_qwen_retry_on_network_error(monkeypatch):
    call_count = 0

    def mock_post(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            request = httpx.Request("POST", "https://mock.test")
            raise httpx.ReadError("SSL: UNEXPECTED_EOF_WHILE_READING", request=request)
        return MockResponse({
            "output": {"embeddings": [{"embedding": [0.1] * 1024}]},
            "usage": {"input_tokens": 42},
        })

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = QwenEmbeddingClient(api_key="fake-key", model="test-model", dimension=1024, max_retries=3)
    with client:
        result = client.embed_text("hello")
        assert result.input_tokens == 42
        assert call_count == 3


def test_qwen_exhaust_retries(monkeypatch):
    call_count = 0

    def mock_post(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("POST", "https://mock.test")
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    client = QwenEmbeddingClient(api_key="fake-key", model="test-model", dimension=1024, max_retries=3)
    with client:
        with pytest.raises(QwenError, match="Could not reach Qwen embedding API"):
            client.embed_text("hello")
    assert call_count == 3
