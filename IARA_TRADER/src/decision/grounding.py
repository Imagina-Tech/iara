"""
GROUNDING SERVICE - Validação de Fatos
Usa Google Search para verificar informações
"""

import logging
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Resultado da verificação de fatos."""
    query: str
    verified: bool
    confidence: float
    sources: List[str]
    summary: str
    timestamp: datetime


class GroundingService:
    """
    Serviço de grounding para validar fatos via Google Search.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o serviço.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self.cx = os.getenv("GOOGLE_SEARCH_CX")  # Custom Search Engine ID
        self._cache: Dict[str, GroundingResult] = {}

    async def verify_claim(self, claim: str, ticker: str = "") -> GroundingResult:
        """
        Verifica uma alegação usando busca web.

        Args:
            claim: Alegação a verificar
            ticker: Ticker relacionado (opcional)

        Returns:
            GroundingResult
        """
        cache_key = f"{ticker}:{claim}"

        # Verifica cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            # Cache válido por 1 hora
            if (datetime.now() - cached.timestamp).seconds < 3600:
                return cached

        try:
            # Monta query de busca
            query = f"{ticker} {claim}" if ticker else claim

            # Executa busca
            search_results = await self._google_search(query)

            # Analisa resultados
            result = self._analyze_results(claim, search_results)

            # Atualiza cache
            self._cache[cache_key] = result

            return result

        except Exception as e:
            logger.error(f"Erro no grounding: {e}")
            return GroundingResult(
                query=claim,
                verified=False,
                confidence=0.0,
                sources=[],
                summary="Erro na verificação",
                timestamp=datetime.now()
            )

    async def _google_search(self, query: str, num_results: int = 5) -> List[Dict]:
        """
        Executa busca no Google.

        Args:
            query: Query de busca
            num_results: Número de resultados

        Returns:
            Lista de resultados
        """
        if not self.api_key or not self.cx:
            logger.warning("Google Search API não configurada")
            return []

        try:
            from googleapiclient.discovery import build

            service = build("customsearch", "v1", developerKey=self.api_key)

            result = service.cse().list(
                q=query,
                cx=self.cx,
                num=num_results
            ).execute()

            return result.get("items", [])

        except Exception as e:
            logger.error(f"Erro na busca Google: {e}")
            return []

    def _analyze_results(self, claim: str, results: List[Dict]) -> GroundingResult:
        """
        Analisa resultados da busca.

        Args:
            claim: Alegação original
            results: Resultados da busca

        Returns:
            GroundingResult
        """
        if not results:
            return GroundingResult(
                query=claim,
                verified=False,
                confidence=0.0,
                sources=[],
                summary="Nenhum resultado encontrado",
                timestamp=datetime.now()
            )

        # Extrai fontes
        sources = []
        snippets = []

        for item in results:
            sources.append(item.get("link", ""))
            snippets.append(item.get("snippet", ""))

        # Análise simples de verificação
        # TODO: Usar IA para análise mais sofisticada
        claim_words = set(claim.lower().split())
        match_count = 0

        for snippet in snippets:
            snippet_words = set(snippet.lower().split())
            if len(claim_words & snippet_words) >= 3:
                match_count += 1

        confidence = min(1.0, match_count / len(results)) if results else 0
        verified = confidence >= 0.5

        return GroundingResult(
            query=claim,
            verified=verified,
            confidence=confidence,
            sources=sources[:3],
            summary=snippets[0] if snippets else "",
            timestamp=datetime.now()
        )

    async def verify_news(self, ticker: str, news_title: str) -> GroundingResult:
        """
        Verifica se uma notícia é real/atual.

        Args:
            ticker: Símbolo do ativo
            news_title: Título da notícia

        Returns:
            GroundingResult
        """
        return await self.verify_claim(news_title, ticker)

    async def check_corporate_action(self, ticker: str, action_type: str) -> GroundingResult:
        """
        Verifica ação corporativa (M&A, dividendos, etc).

        Args:
            ticker: Símbolo do ativo
            action_type: Tipo de ação (merger, dividend, split, etc)

        Returns:
            GroundingResult
        """
        claim = f"{action_type} announcement"
        return await self.verify_claim(claim, ticker)

    def clear_cache(self) -> None:
        """Limpa o cache de verificações."""
        self._cache.clear()
        logger.info("Cache de grounding limpo")
