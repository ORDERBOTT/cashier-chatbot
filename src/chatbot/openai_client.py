from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

import openai
from pydantic import BaseModel

from src.chatbot.exceptions import AIServiceError
from src.chatbot.gemini_client import GeminiFunctionTool, normalize_json_schema
from src.chatbot.llm_messages import LLMMessage, split_system_instruction
from src.config import settings

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_client: openai.AsyncOpenAI | None = None


def _get_client() -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _build_messages(messages: Sequence[LLMMessage]) -> list[dict[str, str]]:
    """Convert LLMMessage list to OpenAI messages format."""
    system_instruction, conversational_messages = split_system_instruction(messages)
    result: list[dict[str, str]] = []
    if system_instruction:
        result.append({"role": "system", "content": system_instruction})
    for msg in conversational_messages:
        role = msg["role"]
        if role == "assistant":
            result.append({"role": "assistant", "content": msg["content"]})
        else:
            result.append({"role": "user", "content": msg["content"]})
    return result


def _build_tools_spec(
    function_tools: Sequence[GeminiFunctionTool],
) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_json_schema,
            },
        }
        for t in function_tools
    ]


async def generate_text(
    messages: Sequence[LLMMessage],
    *,
    temperature: float,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> str:
    resolved_model = model or settings.OPENAI_MODEL
    oai_messages = _build_messages(messages)
    print(
        "[OpenAI] generate_text",
        f"model={resolved_model!r}",
        f"message_turns={len(oai_messages)}",
        f"temperature={temperature}",
        f"max_output_tokens={max_output_tokens!r}",
        "calling chat.completions.create...",
    )
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": oai_messages,
        "temperature": temperature,
    }
    if max_output_tokens is not None:
        kwargs["max_tokens"] = max_output_tokens
    try:
        response = await _get_client().chat.completions.create(**kwargs)
    except openai.OpenAIError as e:
        print("[OpenAI] generate_text raised:", repr(e))
        raise AIServiceError(f"OpenAI request failed: {e}") from e
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise AIServiceError("OpenAI returned empty text content.")
    return content.strip()


async def generate_text_with_tools(
    messages: Sequence[LLMMessage],
    *,
    function_tools: Sequence[GeminiFunctionTool],
    temperature: float,
    max_tool_calls: int,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> str:
    if not function_tools:
        return await generate_text(
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            model=model,
        )

    resolved_model = model or settings.OPENAI_MODEL
    oai_messages = _build_messages(messages)
    tools_spec = _build_tools_spec(function_tools)
    tool_handlers: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
        t.name: t.handler for t in function_tools
    }
    current_messages: list[dict[str, Any]] = list(oai_messages)

    for tool_round in range(max_tool_calls + 1):
        print(
            "[OpenAI] generate_text_with_tools",
            f"model={resolved_model!r}",
            f"tool_round={tool_round}",
            f"message_turns={len(current_messages)}",
            "calling chat.completions.create...",
        )
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": current_messages,
            "temperature": temperature,
            "tools": tools_spec,
            "tool_choice": "auto",
        }
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        try:
            response = await _get_client().chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            print("[OpenAI] generate_text_with_tools raised:", repr(e))
            raise AIServiceError(f"OpenAI request failed: {e}") from e

        choice = response.choices[0]
        print(
            "[OpenAI] generate_text_with_tools response",
            f"finish_reason={choice.finish_reason!r}",
        )

        if choice.finish_reason != "tool_calls":
            content = choice.message.content
            if not content or not content.strip():
                raise AIServiceError("OpenAI returned empty text content.")
            return content.strip()

        if tool_round >= max_tool_calls:
            raise AIServiceError(
                f"OpenAI exceeded the maximum number of tool calls ({max_tool_calls})."
            )

        tool_calls = choice.message.tool_calls or []
        current_messages.append(choice.message.model_dump())

        for tc in tool_calls:
            tool_name = tc.function.name
            if tool_name not in tool_handlers:
                raise AIServiceError(
                    f"OpenAI requested unknown tool: {tool_name!r}."
                )
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                raise AIServiceError(
                    f"OpenAI returned invalid JSON arguments for tool {tool_name!r}: {e}"
                ) from e
            try:
                result = await tool_handlers[tool_name](**args)
            except Exception as exc:  # pragma: no cover
                result = {"success": False, "error": str(exc)}
            current_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                }
            )

    raise AIServiceError(
        f"OpenAI exceeded the maximum number of tool calls ({max_tool_calls})."
    )


async def generate_model(
    messages: Sequence[LLMMessage],
    response_model: type[_ModelT],
    *,
    temperature: float,
    max_output_tokens: int | None = None,
    model: str | None = None,
) -> _ModelT:
    resolved_model = model or settings.OPENAI_MODEL
    oai_messages = _build_messages(messages)
    response_schema = normalize_json_schema(response_model.model_json_schema())
    print(
        "[OpenAI] generate_model",
        f"response_model={getattr(response_model, '__name__', response_model)!r}",
        f"model={resolved_model!r}",
        f"message_turns={len(oai_messages)}",
        f"temperature={temperature}",
        f"max_output_tokens={max_output_tokens!r}",
        "calling chat.completions.create...",
    )
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": oai_messages,
        "temperature": temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": response_schema,
            },
        },
    }
    if max_output_tokens is not None:
        kwargs["max_tokens"] = max_output_tokens
    try:
        response = await _get_client().chat.completions.create(**kwargs)
    except openai.OpenAIError as e:
        print("[OpenAI] generate_model raised:", repr(e))
        raise AIServiceError(f"OpenAI request failed: {e}") from e

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise AIServiceError("OpenAI returned empty structured response.")
    print("[OpenAI] generate_model loading structured payload / validate...")
    try:
        payload = json.loads(content)
        out = response_model.model_validate(payload)
        print("[OpenAI] generate_model validate ok", f"result_type={type(out).__name__}")
        return out
    except Exception as e:
        print("[OpenAI] generate_model validate/payload failed:", repr(e))
        preview = content[:200] if content else None
        if preview:
            raise AIServiceError(
                f"Failed to parse OpenAI structured response: {e}. Raw response preview: {preview!r}"
            ) from e
        raise AIServiceError(f"Failed to parse OpenAI structured response: {e}") from e


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
    if not function_tools:
        return await generate_model(
            messages,
            response_model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            model=model,
        )

    resolved_model = model or settings.OPENAI_MODEL
    oai_messages = _build_messages(messages)
    tools_spec = _build_tools_spec(function_tools)
    response_schema = normalize_json_schema(response_model.model_json_schema())
    tool_handlers: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
        t.name: t.handler for t in function_tools
    }
    current_messages: list[dict[str, Any]] = list(oai_messages)

    for tool_round in range(max_tool_calls + 1):
        print(
            "[OpenAI] generate_model_with_tools",
            f"model={resolved_model!r}",
            f"tool_round={tool_round}",
            f"message_turns={len(current_messages)}",
            "calling chat.completions.create...",
        )
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": current_messages,
            "temperature": temperature,
            "tools": tools_spec,
            "tool_choice": "auto",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        try:
            response = await _get_client().chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            print("[OpenAI] generate_model_with_tools raised:", repr(e))
            raise AIServiceError(f"OpenAI request failed: {e}") from e

        choice = response.choices[0]
        print(
            "[OpenAI] generate_model_with_tools response",
            f"finish_reason={choice.finish_reason!r}",
        )

        if choice.finish_reason != "tool_calls":
            content = choice.message.content
            if not content or not content.strip():
                raise AIServiceError("OpenAI returned empty structured response.")
            try:
                payload = json.loads(content)
                out = response_model.model_validate(payload)
                print(
                    "[OpenAI] generate_model_with_tools validate ok",
                    f"result_type={type(out).__name__}",
                )
                return out
            except Exception as e:
                preview = content[:200] if content else None
                if preview:
                    raise AIServiceError(
                        f"Failed to parse OpenAI structured response: {e}. Raw response preview: {preview!r}"
                    ) from e
                raise AIServiceError(
                    f"Failed to parse OpenAI structured response: {e}"
                ) from e

        if tool_round >= max_tool_calls:
            raise AIServiceError(
                f"OpenAI exceeded the maximum number of tool calls ({max_tool_calls})."
            )

        tool_calls = choice.message.tool_calls or []
        current_messages.append(choice.message.model_dump())

        for tc in tool_calls:
            tool_name = tc.function.name
            if tool_name not in tool_handlers:
                raise AIServiceError(
                    f"OpenAI requested unknown tool: {tool_name!r}."
                )
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                raise AIServiceError(
                    f"OpenAI returned invalid JSON arguments for tool {tool_name!r}: {e}"
                ) from e
            try:
                result = await tool_handlers[tool_name](**args)
            except Exception as exc:  # pragma: no cover
                result = {"success": False, "error": str(exc)}
            current_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                }
            )

    raise AIServiceError(
        f"OpenAI exceeded the maximum number of tool calls ({max_tool_calls})."
    )
