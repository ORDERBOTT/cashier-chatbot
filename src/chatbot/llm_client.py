from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from src.chatbot.gemini_client import GeminiFunctionTool  # re-export: provider-agnostic dataclass
from src.chatbot.llm_messages import LLMMessage
from src.config import settings

_ModelT = TypeVar("_ModelT", bound=BaseModel)

__all__ = [
    "GeminiFunctionTool",
    "generate_text",
    "generate_text_with_tools",
    "generate_model",
    "generate_model_with_tools",
]


def _use_openai() -> bool:
    return settings.AI_MODE.lower() == "chatgpt"


def _resolve_model(gemini_model: str | None) -> str | None:
    """Map a Gemini model name to the corresponding OpenAI model from settings."""
    if gemini_model is None:
        return settings.OPENAI_MODEL
    if gemini_model == settings.PARSING_AGENT_GEMINI_MODEL:
        return settings.PARSING_AGENT_OPENAI_MODEL
    if gemini_model == settings.EXECUTION_AGENT_GEMINI_MODEL:
        return settings.EXECUTION_AGENT_OPENAI_MODEL
    return settings.OPENAI_MODEL


async def generate_text(
    messages: Sequence[LLMMessage],
    *,
    temperature: float,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> str:
    if _use_openai():
        from src.chatbot import openai_client

        return await openai_client.generate_text(
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            model=_resolve_model(model),
        )
    from src.chatbot import gemini_client

    return await gemini_client.generate_text(
        messages,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        model=model,
    )


async def generate_text_with_tools(
    messages: Sequence[LLMMessage],
    *,
    function_tools: Sequence[GeminiFunctionTool],
    temperature: float,
    max_tool_calls: int,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> str:
    if _use_openai():
        from src.chatbot import openai_client

        return await openai_client.generate_text_with_tools(
            messages,
            function_tools=function_tools,
            temperature=temperature,
            max_tool_calls=max_tool_calls,
            max_output_tokens=max_output_tokens,
            model=_resolve_model(model),
        )
    from src.chatbot import gemini_client

    return await gemini_client.generate_text_with_tools(
        messages,
        function_tools=function_tools,
        temperature=temperature,
        max_tool_calls=max_tool_calls,
        max_output_tokens=max_output_tokens,
        model=model,
    )


async def generate_model(
    messages: Sequence[LLMMessage],
    response_model: type[_ModelT],
    *,
    temperature: float,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> _ModelT:
    if _use_openai():
        from src.chatbot import openai_client

        return await openai_client.generate_model(
            messages,
            response_model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            model=_resolve_model(model),
        )
    from src.chatbot import gemini_client

    return await gemini_client.generate_model(
        messages,
        response_model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        model=model,
    )


async def generate_model_with_tools(
    messages: Sequence[LLMMessage],
    response_model: type[_ModelT],
    *,
    function_tools: Sequence[GeminiFunctionTool],
    temperature: float,
    max_tool_calls: int,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> _ModelT:
    if _use_openai():
        from src.chatbot import openai_client

        return await openai_client.generate_model_with_tools(
            messages,
            response_model,
            function_tools=function_tools,
            temperature=temperature,
            max_tool_calls=max_tool_calls,
            max_output_tokens=max_output_tokens,
            model=_resolve_model(model),
        )
    from src.chatbot import gemini_client

    return await gemini_client.generate_model_with_tools(
        messages,
        response_model,
        function_tools=function_tools,
        temperature=temperature,
        max_tool_calls=max_tool_calls,
        max_output_tokens=max_output_tokens,
        model=model,
    )
