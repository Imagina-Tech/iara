"""
AI GATEWAY - Gerenciador de APIs de IA
Hierarquia: Gemini Free -> OpenAI -> Anthropic
"""

import logging
import json
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AIProvider(Enum):
    """Provedores de IA disponíveis."""
    GEMINI = "gemini"
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


class BaseAIClient(ABC):
    """Cliente base para APIs de IA."""

    @abstractmethod
    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa uma completion."""
        pass


class GeminiClient(BaseAIClient):
    """Cliente para Google Gemini."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "gemini-pro"

    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa completion com Gemini."""
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model)

            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

            response = model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                )
            )

            content = response.text
            parsed = self._try_parse_json(content)

            return AIResponse(
                provider=AIProvider.GEMINI,
                model=self.model,
                content=content,
                parsed_json=parsed,
                success=True
            )

        except Exception as e:
            logger.error(f"Erro no Gemini: {e}")
            return AIResponse(
                provider=AIProvider.GEMINI,
                model=self.model,
                content="",
                success=False,
                error=str(e)
            )

    def _try_parse_json(self, content: str) -> Optional[Dict]:
        """Tenta extrair JSON da resposta."""
        try:
            # Procura por blocos de código JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                json_str = content[start:end].strip()
                return json.loads(json_str)
            elif "{" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                return json.loads(content[start:end])
            return None
        except json.JSONDecodeError:
            return None


class OpenAIClient(BaseAIClient):
    """Cliente para OpenAI."""

    def __init__(self, api_key: str, model: str = "gpt-4"):
        self.api_key = api_key
        self.model = model

    async def complete(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.7, max_tokens: int = 2000) -> AIResponse:
        """Executa completion com OpenAI."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            content = response.choices[0].message.content or ""
            parsed = self._try_parse_json(content)

            return AIResponse(
                provider=AIProvider.OPENAI,
                model=self.model,
                content=content,
                parsed_json=parsed,
                tokens_used=response.usage.total_tokens if response.usage else 0,
                success=True
            )

        except Exception as e:
            logger.error(f"Erro no OpenAI: {e}")
            return AIResponse(
                provider=AIProvider.OPENAI,
                model=self.model,
                content="",
                success=False,
                error=str(e)
            )

    def _try_parse_json(self, content: str) -> Optional[Dict]:
        """Tenta extrair JSON da resposta."""
        try:
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                json_str = content[start:end].strip()
                return json.loads(json_str)
            elif "{" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                return json.loads(content[start:end])
            return None
        except json.JSONDecodeError:
            return None


class AIGateway:
    """
    Gateway centralizado para APIs de IA.
    Gerencia fallback e hierarquia de providers.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o gateway.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.clients: Dict[AIProvider, BaseAIClient] = {}
        self._initialize_clients()

    def _initialize_clients(self) -> None:
        """Inicializa clientes de IA disponíveis."""
        # Gemini
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            self.clients[AIProvider.GEMINI] = GeminiClient(gemini_key)
            logger.info("Gemini client inicializado")

        # OpenAI
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            self.clients[AIProvider.OPENAI] = OpenAIClient(openai_key)
            logger.info("OpenAI client inicializado")

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
        for p in [AIProvider.GEMINI, AIProvider.OPENAI, AIProvider.ANTHROPIC]:
            if p not in providers_order and p in self.clients:
                providers_order.append(p)

        for provider in providers_order:
            if provider not in self.clients:
                continue

            response = await self.clients[provider].complete(
                prompt, system_prompt, temperature, max_tokens
            )

            if response.success:
                return response

            logger.warning(f"Falha com {provider.value}, tentando próximo...")

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
