"""LLM client abstraction for the tool-use loop.

The trader depends on the ``LLMClient`` Protocol, never on
``anthropic`` directly. This keeps the agentic loop swappable and
testable: tests inject a ``FakeLLMClient`` that scripts tool calls and
returns canned text.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    name: str
    input: dict[str, Any]
    result: Any


@dataclass(frozen=True, slots=True)
class LLMResult:
    final_text: str
    tool_calls: tuple[ToolCallRecord, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    stop_reason: str = "end_turn"
    iterations: int = 1


class ToolHandler(Protocol):
    """Resolves a single tool call into a JSON-serializable result."""

    def handle(self, tool_name: str, tool_input: dict[str, Any]) -> Any: ...


class LLMClient(Protocol):
    def run_tool_use_loop(
        self,
        *,
        model: str,
        system_blocks: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        initial_user_message: str,
        tool_handler: ToolHandler,
        max_iterations: int = 10,
        max_tokens: int = 2048,
    ) -> LLMResult: ...


# ----------------------------------------------------------------- Anthropic
class AnthropicLLMClient:  # pragma: no cover - thin SDK wrapper
    """Default LLMClient backed by the Anthropic SDK.

    Performs the tool-use loop: dispatches tool_use blocks via the
    handler, feeds tool_result blocks back as the next user message,
    and stops once the model emits ``stop_reason == "end_turn"``.
    """

    def __init__(
        self, client: Any | None = None, client_factory: Callable[[], Any] | None = None
    ) -> None:
        if client is not None:
            self._client = client
            return
        if client_factory is not None:
            self._client = client_factory()
            return
        import anthropic

        self._client = anthropic.Anthropic()

    def run_tool_use_loop(
        self,
        *,
        model: str,
        system_blocks: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        initial_user_message: str,
        tool_handler: ToolHandler,
        max_iterations: int = 10,
        max_tokens: int = 2048,
    ) -> LLMResult:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": initial_user_message}
        ]
        usage = TokenUsage()
        tool_calls: list[ToolCallRecord] = []
        final_text = ""
        stop_reason = "end_turn"

        for i in range(1, max_iterations + 1):
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_blocks,
                tools=tools,
                messages=messages,
            )
            usage = usage + _extract_usage(response)
            stop_reason = response.stop_reason

            if response.stop_reason != "tool_use":
                final_text = _extract_text(response.content)
                return LLMResult(
                    final_text=final_text,
                    tool_calls=tuple(tool_calls),
                    usage=usage,
                    stop_reason=stop_reason,
                    iterations=i,
                )

            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = tool_handler.handle(block.name, dict(block.input))
                tool_calls.append(ToolCallRecord(block.name, dict(block.input), result))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return LLMResult(
            final_text=final_text,
            tool_calls=tuple(tool_calls),
            usage=usage,
            stop_reason="max_iterations",
            iterations=max_iterations,
        )


def _extract_text(content: Any) -> str:
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def _extract_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0)
        or 0,
    )
