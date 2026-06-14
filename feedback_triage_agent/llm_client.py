from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import ValidationError

from feedback_triage_agent.models import FeedbackRecord, LLMFeedbackDraft
from feedback_triage_agent.prompts import SYSTEM_PROMPT, build_feedback_triage_prompt


class LLMUnavailableError(RuntimeError):
    """Raised when the optional LLM provider is not configured."""


class LLMCallError(RuntimeError):
    """Raised when the LLM provider cannot return a valid draft."""


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_seconds: int = 20

    @classmethod
    def from_env(cls) -> "DeepSeekConfig":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise LLMUnavailableError("DEEPSEEK_API_KEY 未设置，使用规则版分诊")
        base_url = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip()
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
        try:
            timeout_seconds = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20"))
        except ValueError as exc:
            raise LLMUnavailableError("DEEPSEEK_TIMEOUT_SECONDS 必须是正整数") from exc
        if not base_url or not model or timeout_seconds <= 0:
            raise LLMUnavailableError("DeepSeek 配置无效，使用规则版分诊")
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
        )


class DeepSeekClient:
    """Minimal DeepSeek Chat Completions client using only stdlib HTTP."""

    def __init__(self, config: Optional[DeepSeekConfig] = None):
        self.config = config or DeepSeekConfig.from_env()

    @property
    def model(self) -> str:
        return self.config.model

    def draft_feedback(self, record: FeedbackRecord) -> LLMFeedbackDraft:
        request = urllib.request.Request(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(self._build_payload(record), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMCallError(f"DeepSeek HTTP {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise LLMCallError(f"DeepSeek 网络调用失败: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMCallError("DeepSeek 调用超时") from exc

        return self._parse_response(response_body)

    def _build_payload(self, record: FeedbackRecord) -> Dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_feedback_triage_prompt(record)},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        }

    def _parse_response(self, response_body: str) -> LLMFeedbackDraft:
        try:
            data = json.loads(response_body)
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMCallError("DeepSeek 响应结构无法解析") from exc

        if not isinstance(content, str):
            raise LLMCallError("DeepSeek 响应内容不是文本")

        try:
            draft_data = json.loads(strip_json_fence(content))
            return LLMFeedbackDraft.model_validate(draft_data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMCallError("DeepSeek 输出不是合法的分诊 JSON") from exc


def strip_json_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned
