"""Real embedding provider: OpenRouter (OpenAI-compatible /embeddings endpoint).

- Same model and same handling for documents and queries (no prefix / instruction).
- Batched requests with retry on transient errors; on persistent failure we RAISE —
  never fall back to mock/random vectors.
- Token usage and cost reported by OpenRouter are accumulated for the report.
"""
import os
import time
from typing import Protocol

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class OpenRouterEmbedder:
    def __init__(self, model_name: str, expected_dimensions: int | None = None,
                 batch_size: int = 64, max_retries: int = 4) -> None:
        key = os.getenv('OPENROUTER_API_KEY')
        if not key:
            raise RuntimeError('OPENROUTER_API_KEY missing (starter/.env)')
        self.client = OpenAI(api_key=key,
                             base_url=os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'))
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.usage = {'requests': 0, 'prompt_tokens': 0, 'cost_usd': 0.0}
        probe = self._call(['kiểm tra số chiều'])[0]      # real call: discover dimensions
        self.dimensions = len(probe)
        if expected_dimensions and self.dimensions != expected_dimensions:
            raise RuntimeError(f'{model_name} returned {self.dimensions} dims, config expects {expected_dimensions}')

    def _call(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.embeddings.create(model=self.model_name, input=texts)
                break
            except (RateLimitError, APIConnectionError) as exc:
                err = exc
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise                       # 4xx (bad key, no credit, bad model): fail loudly
                err = exc
            if attempt == self.max_retries:
                raise RuntimeError(f'embedding failed after {attempt + 1} attempts: {err}') from err
            time.sleep(2 ** attempt)
        data = sorted(resp.data, key=lambda d: d.index)
        if len(data) != len(texts):
            raise RuntimeError(f'provider returned {len(data)} vectors for {len(texts)} inputs')
        u = resp.usage
        self.usage['requests'] += 1
        self.usage['prompt_tokens'] += getattr(u, 'prompt_tokens', 0) or 0
        self.usage['cost_usd'] += float(getattr(u, 'cost', 0) or 0)
        return [d.embedding for d in data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out += self._call(texts[i:i + self.batch_size])
        return out

    def embed_query(self, question: str) -> list[float]:
        return self._call([question])[0]
