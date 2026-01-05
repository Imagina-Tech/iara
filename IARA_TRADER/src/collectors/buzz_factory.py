"""
BUZZ FACTORY - Gerador de Oportunidades (FASE 0)
Gera a lista de oportunidades do dia combinando múltiplas fontes
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BuzzCandidate:
    """Candidato identificado pelo Buzz Factory."""
    ticker: str
    source: str  # "watchlist", "volume_spike", "news", "gap", "momentum"
    buzz_score: float
    reason: str
    detected_at: datetime


class BuzzFactory:
    """
    Fábrica de oportunidades - FASE 0 do pipeline.
    Combina múltiplas fontes para gerar lista de candidatos.
    """

    def __init__(self, config: Dict[str, Any], market_data, news_scraper):
        """
        Inicializa o Buzz Factory.

        Args:
            config: Configurações do sistema
            market_data: Instância do MarketDataCollector
            news_scraper: Instância do NewsScraper
        """
        self.config = config
        self.market_data = market_data
        self.news_scraper = news_scraper

    async def generate_daily_buzz(self) -> List[BuzzCandidate]:
        """
        Gera a lista de oportunidades do dia.

        Returns:
            Lista de candidatos ordenados por buzz_score
        """
        candidates: List[BuzzCandidate] = []
        seen_tickers: Set[str] = set()

        # 1. Adiciona watchlist fixa (Tier 1)
        watchlist_candidates = await self._scan_watchlist()
        for c in watchlist_candidates:
            if c.ticker not in seen_tickers:
                candidates.append(c)
                seen_tickers.add(c.ticker)

        # 2. Scan de Volume Spikes
        volume_candidates = await self._scan_volume_spikes()
        for c in volume_candidates:
            if c.ticker not in seen_tickers:
                candidates.append(c)
                seen_tickers.add(c.ticker)

        # 3. Scan de Gaps
        gap_candidates = await self._scan_gaps()
        for c in gap_candidates:
            if c.ticker not in seen_tickers:
                candidates.append(c)
                seen_tickers.add(c.ticker)

        # 4. Scan de Notícias com Alto Impacto
        news_candidates = await self._scan_news_catalysts()
        for c in news_candidates:
            if c.ticker not in seen_tickers:
                candidates.append(c)
                seen_tickers.add(c.ticker)

        # Ordena por buzz_score decrescente
        candidates.sort(key=lambda x: x.buzz_score, reverse=True)

        logger.info(f"Buzz Factory gerou {len(candidates)} candidatos")
        return candidates

    async def _scan_watchlist(self) -> List[BuzzCandidate]:
        """Escaneia a watchlist fixa."""
        candidates = []

        # TODO: Carregar watchlist do arquivo JSON
        watchlist = []

        for ticker in watchlist:
            data = self.market_data.get_stock_data(ticker)
            if data:
                candidates.append(BuzzCandidate(
                    ticker=ticker,
                    source="watchlist",
                    buzz_score=5.0,  # Score base para watchlist
                    reason="Ativo monitorado na watchlist",
                    detected_at=datetime.now()
                ))

        return candidates

    async def _scan_volume_spikes(self) -> List[BuzzCandidate]:
        """Identifica ativos com volume anormal."""
        candidates = []

        # TODO: Implementar scan de volume
        # Critério: Volume atual > 2x média dos últimos 20 dias

        logger.info("Scanning volume spikes...")
        return candidates

    async def _scan_gaps(self) -> List[BuzzCandidate]:
        """Identifica gaps significativos."""
        candidates = []

        # TODO: Implementar scan de gaps
        # Critério: Gap > 3% em relação ao fechamento anterior

        logger.info("Scanning gaps...")
        return candidates

    async def _scan_news_catalysts(self) -> List[BuzzCandidate]:
        """Identifica ativos com catalisadores de notícias."""
        candidates = []

        # TODO: Implementar scan de notícias
        # Busca por: Earnings, M&A, FDA approvals, etc.

        logger.info("Scanning news catalysts...")
        return candidates

    def apply_filters(self, candidates: List[BuzzCandidate]) -> List[BuzzCandidate]:
        """
        Aplica filtros de liquidez e market cap.

        Args:
            candidates: Lista de candidatos

        Returns:
            Lista filtrada
        """
        filtered = []

        for candidate in candidates:
            # Verifica liquidez
            if not self.market_data.check_liquidity(candidate.ticker):
                logger.debug(f"{candidate.ticker} removido: baixa liquidez")
                continue

            # Verifica se não está na blacklist
            # TODO: Implementar verificação de blacklist

            filtered.append(candidate)

        return filtered
