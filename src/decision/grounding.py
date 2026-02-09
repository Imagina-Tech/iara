"""
GROUNDING SERVICE - Validacao de Fatos
Usa Google Search + Gemini AI para verificar informacoes
"""

import asyncio
import json
import logging
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Resultado da verificacao de fatos."""
    query: str
    verified: bool
    confidence: float
    sources: List[str]
    summary: str
    timestamp: datetime


class GroundingService:
    """
    Servico de grounding para validar fatos via Google Search + Gemini AI.
    Uses AI-based semantic verification with word-matching fallback.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o servico.

        Args:
            config: Configuracoes do sistema
        """
        self.config = config
        self.api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self.cx = os.getenv("GOOGLE_SEARCH_CX")  # Custom Search Engine ID
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self._cache: Dict[str, GroundingResult] = {}

    async def verify_claim(self, claim: str, ticker: str = "") -> GroundingResult:
        """
        Verifica uma alegacao usando busca web + AI.

        Args:
            claim: Alegacao a verificar
            ticker: Ticker relacionado (opcional)

        Returns:
            GroundingResult
        """
        cache_key = f"{ticker}:{claim}"

        # Verifica cache (FIX: .total_seconds() instead of .seconds)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            # Cache valido por 1 hora
            if (datetime.now() - cached.timestamp).total_seconds() < 3600:
                logger.debug(f"[GROUNDING] Cache hit for {ticker}: verified={cached.verified}, conf={cached.confidence:.2f}")
                return cached

        try:
            # Prune expired cache entries periodically (every 100 calls or 1000+ entries)
            if len(self._cache) > 100:
                self._prune_cache()

            # Monta query de busca
            query = f"{ticker} {claim}" if ticker else claim
            logger.info(f"[GROUNDING] Searching: '{query[:80]}...'")

            # Executa busca (async via run_in_executor)
            search_results = await self._google_search(query)
            logger.debug(f"[GROUNDING] Google returned {len(search_results)} results")

            # Analisa resultados com AI (fallback para word-matching)
            result = await self._analyze_results_with_ai(claim, ticker, search_results)

            # Atualiza cache
            self._cache[cache_key] = result

            status = "VERIFIED" if result.verified else "UNVERIFIED"
            logger.info(f"[GROUNDING] {ticker}: {status} (conf={result.confidence:.2f}, "
                        f"{len(result.sources)} sources)")

            return result

        except Exception as e:
            logger.error(f"[GROUNDING] Error verifying '{claim[:60]}': {e}")
            return GroundingResult(
                query=claim,
                verified=False,
                confidence=0.0,
                sources=[],
                summary="Erro na verificacao",
                timestamp=datetime.now()
            )

    async def _google_search(self, query: str, num_results: int = 5) -> List[Dict]:
        """
        Executa busca no Google (async via run_in_executor).

        Args:
            query: Query de busca
            num_results: Numero de resultados

        Returns:
            Lista de resultados
        """
        if not self.api_key or not self.cx:
            logger.warning("[GROUNDING] Google Search API not configured (missing API_KEY or CX)")
            return []

        try:
            from googleapiclient.discovery import build

            loop = asyncio.get_running_loop()

            def _sync_search() -> List[Dict]:
                service = build("customsearch", "v1", developerKey=self.api_key)
                result = service.cse().list(
                    q=query,
                    cx=self.cx,
                    num=num_results
                ).execute()
                return result.get("items", [])

            return await loop.run_in_executor(None, _sync_search)

        except Exception as e:
            logger.error(f"Erro na busca Google: {e}")
            return []

    async def _analyze_results_with_ai(self, claim: str, ticker: str,
                                       search_results: List[Dict]) -> GroundingResult:
        """
        Use Gemini to semantically verify if search results support the claim.
        Falls back to word-matching if Gemini is unavailable or fails.

        Args:
            claim: Alegacao original
            ticker: Ticker relacionado
            search_results: Resultados da busca

        Returns:
            GroundingResult
        """
        if not search_results:
            return GroundingResult(
                query=claim,
                verified=False,
                confidence=0.0,
                sources=[],
                summary="Nenhum resultado encontrado",
                timestamp=datetime.now()
            )

        # Extract sources and snippets
        sources = [item.get("link", "") for item in search_results]
        snippets_text = "\n".join(
            [f"- {r.get('title', '')}: {r.get('snippet', '')}"
             for r in search_results[:5]]
        )

        # Try AI-based verification first
        if self.gemini_key:
            try:
                logger.debug(f"[GROUNDING] Using Gemini AI for semantic verification...")
                ai_result = await self._gemini_verify(claim, ticker, snippets_text, sources)
                if ai_result is not None:
                    logger.debug(f"[GROUNDING] Gemini verification: verified={ai_result.verified}, conf={ai_result.confidence:.2f}")
                    return ai_result
            except Exception as e:
                logger.warning(f"[GROUNDING] Gemini failed, falling back to word-matching: {e}")

        # Fallback: word-matching analysis
        logger.debug(f"[GROUNDING] Using word-matching fallback (less accurate)")
        return self._analyze_results_fallback(claim, search_results)

    async def _gemini_verify(self, claim: str, ticker: str,
                             snippets: str, sources: List[str]) -> Optional[GroundingResult]:
        """
        Call Gemini to semantically verify claim against search results.
        Uses run_in_executor since the Gemini SDK is synchronous.

        Args:
            claim: The claim to verify
            ticker: Related ticker symbol
            snippets: Formatted search result snippets
            sources: List of source URLs

        Returns:
            GroundingResult or None if Gemini fails
        """
        from google import genai
        from google.genai import types

        prompt = (
            f"Verify this financial news claim about {ticker}:\n"
            f"Claim: \"{claim}\"\n\n"
            f"Search results:\n{snippets}\n\n"
            f"Respond ONLY in JSON (no markdown, no code blocks):\n"
            f"{{\n"
            f"  \"verified\": true or false,\n"
            f"  \"confidence\": 0.0 to 1.0,\n"
            f"  \"reasoning\": \"brief explanation\"\n"
            f"}}"
        )

        loop = asyncio.get_running_loop()

        def _sync_gemini_call() -> str:
            client = genai.Client(api_key=self.gemini_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=300,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            return response.text or ""

        raw_response = await loop.run_in_executor(None, _sync_gemini_call)

        # Parse JSON from response
        parsed = self._parse_json_response(raw_response)
        if parsed is None:
            logger.warning(f"Failed to parse Gemini grounding response: {raw_response[:200]}")
            return None

        verified = bool(parsed.get("verified", False))
        confidence = float(parsed.get("confidence", 0.0))
        reasoning = str(parsed.get("reasoning", ""))

        # Clamp confidence to [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))

        return GroundingResult(
            query=claim,
            verified=verified,
            confidence=confidence,
            sources=sources[:3],
            summary=reasoning,
            timestamp=datetime.now()
        )

    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """Try to extract JSON from AI response."""
        try:
            # Try direct parse
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass

        try:
            # Try extracting from code block
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                return json.loads(content[start:end].strip())
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                return json.loads(content[start:end].strip())
            elif "{" in content:
                start = content.find("{")
                end = content.rfind("}") + 1
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    # Stop words to exclude from word-matching (too common, no signal)
    _STOP_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "shall",
        "should", "may", "might", "can", "could", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "about", "between",
        "through", "after", "before", "during", "and", "but", "or", "not",
        "this", "that", "these", "those", "it", "its", "they", "their",
        "stock", "share", "shares", "company", "inc", "corp", "ltd",
    })

    def _analyze_results_fallback(self, claim: str, results: List[Dict]) -> GroundingResult:
        """
        Fallback word-matching analysis when AI is unavailable.
        Uses ratio-based matching with stop word filtering for better accuracy.

        Args:
            claim: Alegacao original
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

        sources = []
        snippets = []

        for item in results:
            sources.append(item.get("link", ""))
            snippets.append(item.get("snippet", ""))

        # Word-matching analysis with stop word filtering
        claim_words = set(claim.lower().split()) - self._STOP_WORDS
        # Need at least 2 meaningful words to match
        if len(claim_words) < 2:
            claim_words = set(claim.lower().split())

        match_count = 0

        for snippet in snippets:
            snippet_words = set(snippet.lower().split()) - self._STOP_WORDS
            overlap = claim_words & snippet_words
            # Require at least 40% of claim words to match AND minimum 3 words
            overlap_ratio = len(overlap) / len(claim_words) if claim_words else 0
            if len(overlap) >= 3 and overlap_ratio >= 0.4:
                match_count += 1

        confidence = min(1.0, match_count / len(results)) if results else 0
        # Reduce confidence from fallback method (AI is more reliable)
        confidence *= 0.7
        verified = confidence >= 0.5

        return GroundingResult(
            query=claim,
            verified=verified,
            confidence=round(confidence, 2),
            sources=sources[:3],
            summary=snippets[0] if snippets else "",
            timestamp=datetime.now()
        )

    async def verify_news(self, ticker: str, news_title: str) -> GroundingResult:
        """
        Verifica se uma noticia e real/atual.

        Args:
            ticker: Simbolo do ativo
            news_title: Titulo da noticia

        Returns:
            GroundingResult
        """
        return await self.verify_claim(news_title, ticker)

    async def check_corporate_action(self, ticker: str, action_type: str) -> GroundingResult:
        """
        Verifica acao corporativa (M&A, dividendos, etc).

        Args:
            ticker: Simbolo do ativo
            action_type: Tipo de acao (merger, dividend, split, etc)

        Returns:
            GroundingResult
        """
        claim = f"{action_type} announcement"
        return await self.verify_claim(claim, ticker)

    def _prune_cache(self) -> None:
        """Remove expired cache entries (> 1 hour old)."""
        now = datetime.now()
        before = len(self._cache)
        self._cache = {k: v for k, v in self._cache.items()
                       if (now - v.timestamp).total_seconds() < 3600}
        pruned = before - len(self._cache)
        if pruned > 0:
            logger.debug(f"Grounding cache pruned: {pruned} expired entries removed")

    def clear_cache(self) -> None:
        """Limpa o cache de verificacoes."""
        self._cache.clear()
        logger.info("Cache de grounding limpo")
