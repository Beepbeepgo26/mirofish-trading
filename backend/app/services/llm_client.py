"""
LLM Client — async OpenAI-compatible interface with rate limiting.
Supports primary (institutional) and boost (retail/noise) model tiers.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI
from app.config import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    usage_prompt: int = 0
    usage_completion: int = 0
    latency_ms: float = 0.0
    raw: Optional[dict] = None


class LLMClient:
    """
    Async LLM client wrapping OpenAI SDK.
    Manages rate limiting via semaphore and retries with exponential backoff.
    """

    def __init__(self, config: LLMConfig, concurrency: int = 10, name: str = "default"):
        self.config = config
        self.name = name
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._semaphore = asyncio.Semaphore(concurrency)
        self._total_calls = 0
        self._total_tokens = 0
        self._errors = 0

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """
        Send a completion request with rate limiting and retry.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(3):
            async with self._semaphore:
                try:
                    t0 = time.monotonic()
                    kwargs = {
                        "model": self.config.model_name,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if response_format:
                        kwargs["response_format"] = response_format

                    response = await self._client.chat.completions.create(**kwargs)
                    latency = (time.monotonic() - t0) * 1000

                    self._total_calls += 1
                    self._total_tokens += (response.usage.prompt_tokens +
                                           response.usage.completion_tokens)

                    return LLMResponse(
                        content=response.choices[0].message.content or "",
                        model=response.model,
                        usage_prompt=response.usage.prompt_tokens,
                        usage_completion=response.usage.completion_tokens,
                        latency_ms=latency,
                    )

                except Exception as e:
                    self._errors += 1
                    wait = 2 ** attempt
                    logger.warning(f"[{self.name}] LLM error (attempt {attempt+1}): {e}. "
                                   f"Retrying in {wait}s...")
                    await asyncio.sleep(wait)

        # All retries failed — return a safe default
        logger.error(f"[{self.name}] LLM failed after 3 attempts.")
        return LLMResponse(content='{"action": "HOLD", "reasoning": "LLM unavailable"}',
                           model="fallback", latency_ms=0)

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 500,
    ) -> dict:
        """
        Get a JSON response from the LLM. Parses and returns dict.
        Falls back to HOLD action on parse failure.
        """
        resp = await self.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        try:
            # Strip markdown fences if present
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            return json.loads(text)
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"[{self.name}] JSON parse failed: {e}. Raw: {resp.content[:200]}")
            return {"action": "HOLD", "reasoning": "Failed to parse LLM response"}

    def stats(self) -> dict:
        return {
            "name": self.name,
            "total_calls": self._total_calls,
            "total_tokens": self._total_tokens,
            "errors": self._errors,
        }
