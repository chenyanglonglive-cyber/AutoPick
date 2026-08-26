from __future__ import annotations

import base64
import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np


EMBEDDING_URL = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
OCR_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


class QwenError(RuntimeError):
    pass


@dataclass
class EmbeddingResult:
    vector: np.ndarray
    input_tokens: int


@dataclass
class OcrResult:
    text: str
    input_tokens: int


class QwenEmbeddingClient:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        dimension: int,
        demo: bool = False,
        max_retries: int = 8,
        timeout: float = 90.0,
    ):
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.demo = demo
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: httpx.Client | None = None

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """Leave enough time for a transient proxy or TLS outage to recover."""
        return min(2 ** (attempt - 1), 30.0) + random.uniform(0.1, 0.4)

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=httpx.Timeout(
                    connect=20.0,
                    read=self.timeout,
                    write=self.timeout,
                    pool=30.0,
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10,
                    keepalive_expiry=30.0,
                ),
                trust_env=True,
            )
        return self._client

    def _reset_client(self) -> None:
        if self._client is not None:
            try:
                if not self._client.is_closed:
                    self._client.close()
            except Exception:
                pass
            self._client = None

    def close(self) -> None:
        self._reset_client()

    def __enter__(self) -> QwenEmbeddingClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def embed_image(self, image_path: Path) -> EmbeddingResult:
        if self.demo:
            return EmbeddingResult(self._demo_vector(image_path.read_bytes()), 0)
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return self._request({"image": f"data:image/jpeg;base64,{encoded}"})

    def embed_text(self, text: str) -> EmbeddingResult:
        if self.demo:
            return EmbeddingResult(self._demo_vector(text.encode("utf-8")), 0)
        return self._request({"text": text})

    def _demo_vector(self, payload: bytes) -> np.ndarray:
        """Deterministic development-only vector. It is never enabled by default."""
        seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "little")
        vector = np.random.default_rng(seed).normal(size=self.dimension).astype(np.float32)
        return vector / np.linalg.norm(vector)

    def _request(self, content: dict[str, str]) -> EmbeddingResult:
        if not self.api_key:
            raise QwenError("DASHSCOPE_API_KEY is not configured. Add it before indexing or searching.")
        payload = {
            "model": self.model,
            "input": {"contents": [content]},
            "parameters": {"dimension": self.dimension, "output_type": "dense"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                client = self._get_client()
                response = client.post(EMBEDDING_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    last_error = exc
                    time.sleep(self._retry_delay(attempt))
                    continue
                detail = exc.response.text
                raise QwenError(f"Qwen embedding request failed ({status}): {detail}") from exc
            except httpx.RequestError as exc:
                last_error = exc
                self._reset_client()
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise QwenError(
                    f"Could not reach Qwen embedding API after {self.max_retries} attempts: {exc}"
                ) from exc
            except Exception as exc:
                self._reset_client()
                raise QwenError(f"Unexpected error when calling Qwen API: {exc}") from exc
        else:
            raise QwenError(f"Qwen embedding request failed after {self.max_retries} attempts: {last_error}")

        output = data.get("output", {})
        embeddings = output.get("embeddings") or output.get("embedding") or []
        if isinstance(embeddings, dict):
            embeddings = [embeddings]
        if not embeddings:
            raise QwenError(f"Unexpected Qwen response: {data}")
        vector = embeddings[0].get("embedding") or embeddings[0].get("vector")
        if not vector:
            raise QwenError(f"Qwen response did not contain a vector: {data}")
        values = np.asarray(vector, dtype=np.float32)
        if values.size != self.dimension:
            raise QwenError(f"Expected {self.dimension} dimensions, got {values.size}.")
        norm = np.linalg.norm(values)
        if norm == 0:
            raise QwenError("Qwen returned a zero vector.")
        usage = data.get("usage", {})
        token_count = int(usage.get("input_tokens", usage.get("total_tokens", 0)) or 0)
        return EmbeddingResult(values / norm, token_count)


class QwenOcrClient:
    """Small HTTP client for Qwen OCR; results never leave the current project DB."""

    def __init__(self, api_key: str | None, model: str = "qwen-vl-ocr", demo: bool = False, timeout: float = 90.0):
        self.api_key = api_key
        self.model = model
        self.demo = demo
        self.timeout = timeout

    def extract_text(self, image_path: Path) -> OcrResult:
        if self.demo:
            return OcrResult("", 0)
        if not self.api_key:
            raise QwenError("DASHSCOPE_API_KEY is not configured. Add it before OCR.")
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    {"type": "text", "text": "请准确提取图片中所有可辨识的文字。只输出文字内容，不要解释；看不清的部分可省略。"},
                ],
            }],
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(timeout=httpx.Timeout(self.timeout), trust_env=True) as client:
                    response = client.post(OCR_URL, json=payload, headers=headers)
                    response.raise_for_status()
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        str(part.get("text", "")) for part in content if isinstance(part, dict)
                    )
                usage = data.get("usage", {})
                tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", usage.get("total_tokens", 0))) or 0)
                return OcrResult(" ".join(str(content).split()), tokens)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise QwenError(f"Qwen OCR request failed ({exc.response.status_code}): {exc.response.text}") from exc
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == 3:
                    raise QwenError(f"Could not reach Qwen OCR API: {exc}") from exc
            time.sleep((2 ** (attempt - 1)) + random.uniform(0.1, 0.4))
        raise QwenError(f"Qwen OCR request failed: {last_error}")


