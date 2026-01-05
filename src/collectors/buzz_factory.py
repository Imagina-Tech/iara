"""
BUZZ FACTORY - Gerador de Oportunidades (FASE 0)
Gera a lista de oportunidades do dia combinando múltiplas fontes
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class BuzzCandidate:
    """Candidato identificado pelo Buzz Factory."""
    ticker: str
    source: str  # "watchlist", "volume_spike", "news", "gap", "momentum"
    buzz_score: float
    reason: str
    detected_at: datetime
    tier: str = "unknown"  # "tier1_large_cap", "tier2_mid_cap"
    market_cap: float = 0.0  # Market cap in dollars


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
        """Escaneia a watchlist fixa do arquivo config/watchlist.json."""
        candidates = []

        try:
            # Carregar watchlist do arquivo JSON
            watchlist_path = PROJECT_ROOT / "config" / "watchlist.json"

            if not watchlist_path.exists():
                logger.warning(f"Watchlist file not found: {watchlist_path}")
                return candidates

            with open(watchlist_path, "r") as f:
                watchlist_data = json.load(f)

            # Processar apenas Tier 1 (Blue Chips)
            tier1_tickers = watchlist_data.get("tier1_large_cap", [])
            logger.info(f"Loading {len(tier1_tickers)} tickers from watchlist")

            # Verificar cada ticker
            for ticker in tier1_tickers:
                try:
                    data = self.market_data.get_stock_data(ticker)

                    if not data:
                        logger.debug(f"{ticker}: No market data available")
                        continue

                    # Verificar market cap mínimo ($4B para Tier 1)
                    tier_config = self.config.get("tiers", {}).get("tier1_large_cap", {})
                    min_market_cap = tier_config.get("min_market_cap", 4_000_000_000)

                    if hasattr(data, 'market_cap') and data.market_cap:
                        if data.market_cap < min_market_cap:
                            logger.debug(f"{ticker}: Market cap ${data.market_cap/1e9:.2f}B below Tier 1 threshold")
                            continue

                    # Criar candidato
                    market_cap_value = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0
                    candidates.append(BuzzCandidate(
                        ticker=ticker,
                        source="watchlist",
                        buzz_score=5.0,  # Score base para watchlist
                        reason=f"Tier 1 watchlist asset (${market_cap_value/1e9:.1f}B cap)" if market_cap_value > 0 else "Tier 1 watchlist asset",
                        detected_at=datetime.now(),
                        tier="tier1_large_cap",
                        market_cap=market_cap_value
                    ))

                    logger.debug(f"{ticker}: Added to candidates from watchlist")

                except Exception as e:
                    logger.error(f"Error processing {ticker} from watchlist: {e}")
                    continue

            logger.info(f"Watchlist scan complete: {len(candidates)} candidates")

        except Exception as e:
            logger.error(f"Error scanning watchlist: {e}")

        return candidates

    async def _scan_volume_spikes(self) -> List[BuzzCandidate]:
        """
        Identifica ativos com volume anormal.

        Critério: Volume atual > 2x média dos últimos 20 dias
        """
        candidates = []

        try:
            phase0_config = self.config.get("phase0", {})
            volume_multiplier = phase0_config.get("volume_spike_multiplier", 2.0)
            min_dollar_volume = self.config.get("liquidity", {}).get("min_dollar_volume", 15_000_000)

            logger.info(f"Scanning volume spikes (>{volume_multiplier}x average)...")

            # Universo de tickers para escanear
            # Opção 1: S&P 500 (simplified - top 100 por volume)
            # Opção 2: Lista fixa de tickers populares
            # Opção 3: Download dinâmico (mais complexo)

            # Por enquanto, usar lista fixa de tickers populares
            universe = self._get_scan_universe()

            scanned = 0
            for ticker in universe:
                try:
                    data = self.market_data.get_stock_data(ticker)

                    if not data:
                        continue

                    scanned += 1

                    # Calcular volume ratio
                    if hasattr(data, 'volume') and hasattr(data, 'avg_volume_20d'):
                        volume_ratio = data.volume / data.avg_volume_20d if data.avg_volume_20d > 0 else 0

                        # Verificar critérios
                        if volume_ratio >= volume_multiplier:
                            # Verificar dollar volume
                            dollar_volume = data.volume * data.price if hasattr(data, 'price') else 0

                            if dollar_volume >= min_dollar_volume:
                                # Determine tier based on market cap
                                market_cap_value = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0
                                tier_config = self.config.get("tiers", {})
                                tier1_min = tier_config.get("tier1_large_cap", {}).get("min_market_cap", 4_000_000_000)

                                if market_cap_value >= tier1_min:
                                    tier = "tier1_large_cap"
                                else:
                                    tier = "tier2_mid_cap"

                                candidates.append(BuzzCandidate(
                                    ticker=ticker,
                                    source="volume_spike",
                                    buzz_score=7.0 + min(volume_ratio, 5.0),  # Score 7-12 baseado em volume
                                    reason=f"Volume spike {volume_ratio:.1f}x (${dollar_volume/1e6:.1f}M)",
                                    detected_at=datetime.now(),
                                    tier=tier,
                                    market_cap=market_cap_value
                                ))

                                logger.debug(f"{ticker}: Volume spike {volume_ratio:.1f}x detected")

                except Exception as e:
                    logger.debug(f"Error scanning {ticker}: {e}")
                    continue

            logger.info(f"Volume scan complete: {scanned} scanned, {len(candidates)} spikes found")

        except Exception as e:
            logger.error(f"Error in volume spike scan: {e}")

        return candidates

    def _get_scan_universe(self) -> List[str]:
        """
        Retorna universo de tickers para escanear.

        Por enquanto retorna lista fixa de tickers populares.
        No futuro, pode ser expandido para S&P 500 completo.
        """
        # Top 100 tickers por volume (lista simplificada)
        return [
            # Tech giants
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            # Finance
            "JPM", "BAC", "WFC", "C", "GS", "MS",
            # Healthcare
            "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO",
            # Consumer
            "WMT", "HD", "DIS", "NKE", "SBUX", "MCD",
            # Energy
            "XOM", "CVX", "COP", "SLB",
            # Industrial
            "BA", "CAT", "GE", "HON", "UPS",
            # Popular ETFs
            "SPY", "QQQ", "DIA", "IWM",
            # Meme/Popular stocks
            "GME", "AMC", "PLTR", "RIVN", "LCID",
            # Crypto-related
            "COIN", "MSTR",
            # Additional tech
            "AMD", "INTC", "CSCO", "ORCL", "CRM", "ADBE",
            # Semiconductors
            "TSM", "ASML", "QCOM", "AVGO", "MU",
            # EVs
            "F", "GM", "NIO", "XPEV",
            # Pharma
            "LLY", "BMY", "GILD", "REGN",
            # Retail
            "TGT", "COST", "LULU",
            # Telecom
            "T", "VZ", "TMUS"
        ]

    async def _scan_gaps(self) -> List[BuzzCandidate]:
        """
        Identifica gaps significativos no pré-mercado ou abertura.

        Critério: Gap > 3% em relação ao fechamento anterior
        """
        candidates = []

        try:
            phase0_config = self.config.get("phase0", {})
            gap_threshold = phase0_config.get("gap_threshold", 0.03)

            # Verificar se é horário de pré-mercado ou abertura
            now = datetime.now()
            market_open_time = datetime.strptime("09:30", "%H:%M").time()
            premarket_start = datetime.strptime("08:00", "%H:%M").time()

            # Executar apenas durante pré-mercado (08:00-09:30) ou nos primeiros 30min após abertura
            is_premarket = premarket_start <= now.time() < market_open_time
            is_early_market = (now.time() >= market_open_time and
                               (now - datetime.combine(now.date(), market_open_time)).seconds < 1800)

            if not (is_premarket or is_early_market):
                logger.debug("Gap scan skipped: not in premarket/early market hours")
                return candidates

            logger.info(f"Scanning gaps (>{gap_threshold*100:.1f}%)...")

            # Escanear universo de tickers
            universe = self._get_scan_universe()

            scanned = 0
            for ticker in universe:
                try:
                    data = self.market_data.get_stock_data(ticker)

                    if not data:
                        continue

                    scanned += 1

                    # Calcular gap percentage
                    if hasattr(data, 'price') and hasattr(data, 'previous_close'):
                        if data.previous_close and data.previous_close > 0:
                            gap_pct = (data.price - data.previous_close) / data.previous_close

                            # Verificar se gap é significativo (positivo ou negativo)
                            if abs(gap_pct) >= gap_threshold:
                                gap_direction = "up" if gap_pct > 0 else "down"

                                # Determine tier based on market cap
                                market_cap_value = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0
                                tier_config = self.config.get("tiers", {})
                                tier1_min = tier_config.get("tier1_large_cap", {}).get("min_market_cap", 4_000_000_000)

                                if market_cap_value >= tier1_min:
                                    tier = "tier1_large_cap"
                                else:
                                    tier = "tier2_mid_cap"

                                candidates.append(BuzzCandidate(
                                    ticker=ticker,
                                    source="gap",
                                    buzz_score=8.0 + min(abs(gap_pct) * 10, 5.0),  # Score 8-13 baseado em gap
                                    reason=f"Gap {gap_direction} {gap_pct*100:.1f}% (${data.price:.2f} vs ${data.previous_close:.2f})",
                                    detected_at=datetime.now(),
                                    tier=tier,
                                    market_cap=market_cap_value
                                ))

                                logger.debug(f"{ticker}: Gap {gap_direction} {gap_pct*100:.1f}% detected")

                except Exception as e:
                    logger.debug(f"Error scanning {ticker} for gaps: {e}")
                    continue

            logger.info(f"Gap scan complete: {scanned} scanned, {len(candidates)} gaps found")

        except Exception as e:
            logger.error(f"Error in gap scan: {e}")

        return candidates

    async def _scan_news_catalysts(self) -> List[BuzzCandidate]:
        """
        Identifica ativos com catalisadores de notícias.

        Busca por: Earnings, M&A, FDA approvals, partnerships, etc.
        Usa NewsAggregator com Gemini NLP para extrair tickers.
        """
        candidates = []

        try:
            logger.info("Scanning news catalysts...")

            # Importar NewsAggregator
            from src.collectors.news_aggregator import NewsAggregator

            # Criar instância (sem AI gateway por enquanto - apenas keywords)
            aggregator = NewsAggregator(self.config)

            # Buscar notícias com catalisadores
            catalyst_news = await aggregator.find_catalyst_news(
                keywords=["earnings", "FDA approval", "merger", "acquisition",
                          "partnership", "breakthrough", "buyback", "guidance"]
            )

            # Converter NewsArticle para BuzzCandidate
            for article in catalyst_news:
                for ticker in article.tickers_mentioned:
                    # Verificar se ticker já foi adicionado
                    if not any(c.ticker == ticker for c in candidates):
                        # Get market data for tier and market cap
                        data = self.market_data.get_stock_data(ticker)
                        market_cap_value = 0.0
                        tier = "unknown"

                        if data and hasattr(data, 'market_cap') and data.market_cap:
                            market_cap_value = data.market_cap
                            tier_config = self.config.get("tiers", {})
                            tier1_min = tier_config.get("tier1_large_cap", {}).get("min_market_cap", 4_000_000_000)

                            if market_cap_value >= tier1_min:
                                tier = "tier1_large_cap"
                            else:
                                tier = "tier2_mid_cap"

                        candidates.append(BuzzCandidate(
                            ticker=ticker,
                            source="news_catalyst",
                            buzz_score=article.relevance_score,  # 8.0+ para catalysts
                            reason=f"Catalyst: {article.title[:80]}...",
                            detected_at=datetime.now(),
                            tier=tier,
                            market_cap=market_cap_value
                        ))

                        logger.debug(f"{ticker}: Catalyst news detected - {article.title[:50]}...")

            logger.info(f"News catalyst scan complete: {len(candidates)} candidates from {len(catalyst_news)} articles")

        except Exception as e:
            logger.error(f"Error in news catalyst scan: {e}")

        return candidates

    async def apply_filters(self, candidates: List[BuzzCandidate]) -> List[BuzzCandidate]:
        """
        Aplica filtros de market cap, liquidez, Friday blocking e earnings proximity.

        Args:
            candidates: Lista de candidatos

        Returns:
            Lista filtrada
        """
        filtered = []

        # Importar EarningsChecker
        from src.collectors.earnings_checker import EarningsChecker
        earnings_checker = EarningsChecker(self.config)

        # Config
        phase0_config = self.config.get("phase0", {})
        friday_block = phase0_config.get("friday_block", True)
        tier1_config = self.config.get("tiers", {}).get("tier1_large_cap", {})
        tier2_config = self.config.get("tiers", {}).get("tier2_mid_cap", {})
        min_tier1_cap = tier1_config.get("min_market_cap", 4_000_000_000)
        min_tier2_cap = tier2_config.get("min_market_cap", 800_000_000)

        # Verificar Friday blocking
        now = datetime.now()
        is_friday = now.weekday() == 4

        if is_friday and friday_block:
            logger.warning("🚫 FRIDAY BLOCKING ACTIVE - No new entries allowed")
            return []

        for candidate in candidates:
            ticker = candidate.ticker

            try:
                # 1. Verificar market cap e classificar tier
                data = self.market_data.get_stock_data(ticker)

                if not data:
                    logger.debug(f"{ticker} rejected: no market data")
                    continue

                # Market cap filtering e tier classification
                if hasattr(data, 'market_cap') and data.market_cap:
                    if data.market_cap < min_tier2_cap:
                        logger.debug(f"{ticker} rejected: market cap ${data.market_cap/1e9:.2f}B < ${min_tier2_cap/1e9:.1f}B")
                        continue

                    # Classificar tier
                    if data.market_cap >= min_tier1_cap:
                        candidate.tier = "tier1_large_cap"
                    else:
                        candidate.tier = "tier2_mid_cap"

                # 2. Verificar liquidez
                if not await self.market_data.check_liquidity(ticker):
                    logger.debug(f"{ticker} rejected: low liquidity")
                    continue

                # 3. Verificar earnings proximity (< 5 dias)
                if earnings_checker.check_earnings_proximity(ticker):
                    logger.debug(f"{ticker} rejected: earnings within 5 days")
                    continue

                # 4. Verificar blacklist (se existir)
                # TODO: Implementar blacklist check se necessário

                # Candidato passou em todos os filtros
                filtered.append(candidate)
                logger.debug(f"{ticker} passed all filters (tier: {getattr(candidate, 'tier', 'unknown')})")

            except Exception as e:
                logger.error(f"Error filtering {ticker}: {e}")
                continue

        logger.info(f"Filtering complete: {len(filtered)}/{len(candidates)} candidates passed")

        return filtered
