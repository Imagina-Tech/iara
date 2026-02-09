"""
AI GATEWAY - Gerenciador de APIs de IA
Hierarquia: Gemini Free -> OpenAI -> Anthropic
"""

import logging
import json
import re
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AIProvider(Enum):
    """Provedores de IA disponíveis."""
    GEMINI = "gemini"
    GEMINI_PRO = "gemini_pro"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class AIResponse:
    """Resposta padronizada de IA."""
    provider: AIProvider
    model: str
    content: str
    parsed_json: Optional[Dict] = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


def _try_parse_json(content: str) -> Optional[Dict]:
    """
    Robust JSON extraction from AI response text.
    Handles: ```json blocks, raw JSON, nested braces, markdown wrapping.
    """
    if not content or not content.strip():
        return None

    try:
        # Strategy 1: Extract from ```json ... ``` blocks (greedy for content)
        json_block_match = re.search(r'```json\s*\n?(.*?)\n?\s*```', content, re.DOTALL)
        if json_block_match:
            json_str = json_block_match.group(1).strip()
            return json.loads(json_str)

        # Strategy 2: Extract from ``` ... ``` blocks (without json tag)
        code_block_match = re.search(r'```\s*\n?(.*?)\n?\s*```', content, re.DOTALL)
        if code_block_match:
            json_str = code_block_match.group(1).strip()
            if json_str.startswith('{'):
                return json.loads(json_str)

        # Strategy 3: Find outermost { ... } using brace counting
        first_brace = content.find('{')
        if first_brace != -1:
            depth = 0
            for i in range(first_brace, len(content)):
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                    if depth == 0:
                        json_str = content[first_brace:i + 1]
                        return json.loads(json_str)

        return None
    except (json.JSONDecodeError, ValueError):
        return None


class BaseAIClient(ABC):
    """Cliente base para APIs de IA."""

    @abstractmethod
    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa uma completion."""
        pass


class GeminiClient(BaseAIClient):
    """Cliente para Google Gemini (using google-genai SDK)."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa completion com Gemini (non-blocking via run_in_executor)."""
        try:
            from google import genai
            from google.genai import types
            import asyncio

            client = genai.Client(api_key=self.api_key)

            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

            # Gemini 3 Pro requires thinking mode; Flash models need it disabled
            # to avoid thinking tokens consuming the output budget.
            # For thinking models, max_output_tokens must cover BOTH thinking
            # tokens AND the actual response, otherwise the JSON gets truncated.
            is_thinking_model = "3-pro" in self.model
            if is_thinking_model:
                thinking_budget = 8192
                gen_config = types.GenerateContentConfig(
                    max_output_tokens=thinking_budget + max_tokens,
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget)
                )
            else:
                gen_config = types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )

            # Run sync Gemini call in executor to not block the event loop
            loop = asyncio.get_running_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=self.model,
                        contents=full_prompt,
                        config=gen_config
                    )
                ),
                timeout=self.timeout
            )

            # Extract text - handle thinking models gracefully
            content = ""
            try:
                content = response.text or ""
            except (ValueError, AttributeError):
                # Fallback: manually extract text from parts (skip thought parts)
                if response.candidates:
                    for part in response.candidates[0].content.parts:
                        if getattr(part, 'thought', False):
                            continue
                        if hasattr(part, 'text') and part.text:
                            content += part.text

            if not content:
                logger.warning(f"[AI-GATEWAY] Gemini returned empty content (model={self.model})")

            parsed = _try_parse_json(content)

            # Token counting from usage metadata
            tokens = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                tokens = getattr(response.usage_metadata, 'total_token_count', 0) or 0

            return AIResponse(
                provider=AIProvider.GEMINI,
                model=self.model,
                content=content,
                parsed_json=parsed,
                tokens_used=tokens,
                success=True
            )

        except Exception as e:
            logger.error(f"[AI-GATEWAY] Gemini error: {type(e).__name__}: {str(e)[:150]}")
            return AIResponse(
                provider=AIProvider.GEMINI,
                model=self.model,
                content="",
                success=False,
                error=str(e)
            )


class OpenAIClient(BaseAIClient):
    """Cliente para OpenAI."""

    def __init__(self, api_key: str, model: str = "gpt-5.2"):
        self.api_key = api_key
        self.model = model

    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa completion com OpenAI."""
        try:
            from openai import AsyncOpenAI
            import httpx

            client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=httpx.Timeout(30.0, connect=10.0)
            )

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens
            )

            content = response.choices[0].message.content or ""
            parsed = _try_parse_json(content)

            return AIResponse(
                provider=AIProvider.OPENAI,
                model=self.model,
                content=content,
                parsed_json=parsed,
                tokens_used=response.usage.total_tokens if response.usage else 0,
                success=True
            )

        except Exception as e:
            logger.error(f"[AI-GATEWAY] OpenAI error: {type(e).__name__}: {str(e)[:150]}")
            return AIResponse(
                provider=AIProvider.OPENAI,
                model=self.model,
                content="",
                success=False,
                error=str(e)
            )


class AnthropicClient(BaseAIClient):
    """Cliente para Anthropic Claude."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5"):
        self.api_key = api_key
        self.model = model

    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa completion com Claude."""
        try:
            from anthropic import AsyncAnthropic
            import httpx

            client = AsyncAnthropic(
                api_key=self.api_key,
                timeout=httpx.Timeout(30.0, connect=10.0)
            )

            messages = [{"role": "user", "content": prompt}]

            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            response = await client.messages.create(**kwargs)

            content = response.content[0].text if response.content else ""
            parsed = _try_parse_json(content)

            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0

            return AIResponse(
                provider=AIProvider.ANTHROPIC,
                model=self.model,
                content=content,
                parsed_json=parsed,
                tokens_used=input_tokens + output_tokens,
                success=True
            )

        except Exception as e:
            logger.error(f"[AI-GATEWAY] Anthropic error: {type(e).__name__}: {str(e)[:150]}")
            return AIResponse(
                provider=AIProvider.ANTHROPIC,
                model=self.model,
                content="",
                success=False,
                error=str(e)
            )


class AIGateway:
    """
    Gateway centralizado para APIs de IA.
    Gerencia fallback e hierarquia de providers.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o gateway.

        Args:
            config: Configuracoes do sistema
        """
        self.config = config
        self.clients: Dict[AIProvider, BaseAIClient] = {}
        self._initialize_clients()

    def _initialize_clients(self) -> None:
        """Inicializa clientes de IA disponiveis."""
        # Gemini Flash (free/cheap - for Screener)
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            self.clients[AIProvider.GEMINI] = GeminiClient(gemini_key)
            logger.info("[AI-GATEWAY] Gemini Flash initialized (gemini-2.5-flash)")

            # Gemini Pro (paid - for Judge: 1M input, 65K output)
            self.clients[AIProvider.GEMINI_PRO] = GeminiClient(
                gemini_key, model="gemini-3-pro-preview", timeout=90.0
            )
            logger.info("[AI-GATEWAY] Gemini Pro initialized (gemini-3-pro-preview)")

        # OpenAI
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            self.clients[AIProvider.OPENAI] = OpenAIClient(openai_key)
            logger.info("[AI-GATEWAY] OpenAI client initialized (gpt-5.2)")

        # Anthropic
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            self.clients[AIProvider.ANTHROPIC] = AnthropicClient(anthropic_key)
            logger.info("[AI-GATEWAY] Anthropic client initialized (claude-sonnet-4-5)")

        available = [p.value for p in self.clients.keys()]
        logger.info(f"[AI-GATEWAY] {len(self.clients)} providers ready: {', '.join(available)}")

    async def complete(self, prompt: str, system_prompt: str = "",
                       preferred_provider: AIProvider = AIProvider.GEMINI,
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """
        Executa completion com fallback automático.

        Args:
            prompt: Prompt do usuário
            system_prompt: Prompt de sistema
            preferred_provider: Provider preferido
            temperature: Temperatura
            max_tokens: Máximo de tokens

        Returns:
            AIResponse
        """
        # Ordem de tentativa
        providers_order = [preferred_provider]
        for p in [AIProvider.GEMINI_PRO, AIProvider.GEMINI, AIProvider.OPENAI, AIProvider.ANTHROPIC]:
            if p not in providers_order and p in self.clients:
                providers_order.append(p)

        fallback_chain = [p.value for p in providers_order if p in self.clients]
        logger.debug(f"[AI-GATEWAY] Fallback chain: {' -> '.join(fallback_chain)} (temp={temperature})")

        import time as _time
        for idx, provider in enumerate(providers_order):
            if provider not in self.clients:
                continue

            attempt_label = "PRIMARY" if idx == 0 else f"FALLBACK #{idx}"
            logger.info(f"[AI-GATEWAY] {attempt_label}: Calling {provider.value} (max_tokens={max_tokens})...")

            t0 = _time.perf_counter()
            response = await self.clients[provider].complete(
                prompt, system_prompt, temperature, max_tokens
            )
            elapsed_ms = (_time.perf_counter() - t0) * 1000

            if response.success:
                json_status = "JSON parsed" if response.parsed_json else "plain text"
                logger.info(f"[AI-GATEWAY] {provider.value} OK ({elapsed_ms:.0f}ms, "
                            f"{response.tokens_used} tokens, {json_status})")
                return response

            logger.warning(f"[AI-GATEWAY] {provider.value} FAILED ({elapsed_ms:.0f}ms): {response.error}")

        logger.error("[AI-GATEWAY] ALL PROVIDERS FAILED - no AI available")
        return AIResponse(
            provider=AIProvider.GEMINI,
            model="none",
            content="",
            success=False,
            error="Todos os providers falharam"
        )

    def get_available_providers(self) -> List[AIProvider]:
        """Retorna lista de providers disponíveis."""
        return list(self.clients.keys())
