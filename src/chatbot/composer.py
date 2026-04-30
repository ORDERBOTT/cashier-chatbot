from __future__ import annotations

import json
from typing import Any

from src.chatbot import llm_client
from src.chatbot.composer_prompt import build_composer_system_prompt
from src.chatbot.composer_tools import build_composer_tools
from src.chatbot.exceptions import AIServiceError
from src.chatbot.llm_messages import LLMMessage
from src.chatbot.schema import (
    ComposerInput,
    ComposerOutput,
    MerchantPersona,
    OrderingStage,
)
from src.config import settings


class ComposerError(Exception):
    """Raised when the Composer cannot produce a usable ComposerOutput.

    Distinct from AIServiceError so the orchestrator can decide policy:
    AIServiceError is a transient infrastructure failure and is retried by
    the existing helper; ComposerError indicates the model returned but its
    output could not be parsed or validated.
    """


_DEFAULT_MAX_TOOL_CALLS = 8


class Composer:
    def __init__(
        self,
        *,
        model: str | None = None,
        persona: MerchantPersona | None = None,
        max_tool_calls: int = _DEFAULT_MAX_TOOL_CALLS,
    ) -> None:
        self.model = model or (
            settings.COMPOSER_AGENT_OPENAI_MODEL
            if settings.AI_MODE.lower() == "chatgpt"
            else settings.EXECUTION_AGENT_GEMINI_MODEL
        )
        # Persona is required to build the system prompt. Allow construction
        # without one for testing; voice() will raise if invoked without it.
        self.persona = persona
        self.max_tool_calls = max_tool_calls
        self._cached_system_prompt: str | None = None

    def _system_prompt(self, persona: MerchantPersona) -> str:
        # Cache per-instance: persona is immutable per Composer construction.
        if self._cached_system_prompt is None:
            self._cached_system_prompt = build_composer_system_prompt(persona)
        return self._cached_system_prompt

    async def voice(
        self,
        composer_input: ComposerInput,
        *,
        creds: dict | None = None,
    ) -> ComposerOutput:
        """Run the Composer end-to-end and return a validated ComposerOutput.

        creds is the Clover creds dict needed by some tools (confirmOrder,
        though confirmOrder_guarded only uses it on success path). It is
        passed separately because it is sensitive and not part of the
        Composer's reasoning input.
        """
        persona = composer_input.persona or self.persona
        if persona is None:
            raise ComposerError(
                "Composer.voice requires a persona either on the instance "
                "or in composer_input.persona"
            )

        system_prompt = self._system_prompt(persona)
        user_content = self._render_user_content(composer_input)
        messages: list[LLMMessage] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        tools = build_composer_tools(composer_input, creds=creds)

        try:
            raw_text = await llm_client.generate_text_with_tools(
                messages,
                function_tools=tools,
                temperature=0.4,
                max_tool_calls=self.max_tool_calls,
                model=self.model,
            )
        except AIServiceError:
            # Let infrastructure errors propagate — the orchestrator wraps
            # the call in _gemini_service_call_with_retries.
            raise

        return self._parse_output(raw_text)

    @staticmethod
    def _render_user_content(composer_input: ComposerInput) -> str:
        # Serialize the input as JSON for the model. Exclude the persona
        # because it is already baked into the system prompt; including it
        # in the user message wastes tokens and risks the model echoing it.
        # Also exclude the merchant_id for the same reason — it's not a
        # decision input for the Composer.
        payload = composer_input.model_dump(
            mode="json",
            exclude={"persona", "merchant_id", "phone_number", "firebase_uid"},
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _parse_output(raw_text: str) -> ComposerOutput:
        cleaned = Composer._strip_markdown_fences(raw_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ComposerError(
                f"Composer returned non-JSON output: {raw_text[:500]!r}"
            ) from exc
        try:
            return ComposerOutput.model_validate(data)
        except Exception as exc:
            raise ComposerError(
                f"Composer output failed schema validation: {data!r}"
            ) from exc

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Strip ```json ... ``` fences if the model returned them despite
        instructions. Models occasionally do this; we handle it instead of
        treating it as a fatal error.
        """
        s = text.strip()
        if s.startswith("```"):
            # Remove first line (```json or ```)
            lines = s.split("\n", 1)
            if len(lines) == 2:
                s = lines[1]
            # Remove trailing fence
            if s.rstrip().endswith("```"):
                s = s.rstrip()[: -3].rstrip()
        return s