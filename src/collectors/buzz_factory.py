"""
BUZZ FACTORY - Gerador de Oportunidades (FASE 0)
Gera a lista de oportunidades do dia combinando multiplas fontes

Arquitetura de Cache (2026-01-06):
- _market_data_cache: Cache de dados de mercado por ticker (limpo a cada ciclo)
- _news_cache: Cache de noticias por ticker (limpo a cada ciclo)
- Evita chamadas duplicadas ao yfinance durante um ciclo de scan
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

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
    news_content: str = ""  # Conteudo das noticias relacionadas (para passar ao Screener/Judge)


class BuzzFactory:
    """
    Fabrica de oportunidades - FASE 0 do pipeline.
    Combina multiplas fontes para gerar lista de candidatos.

    Otimizacoes implementadas:
    - Cache de market data durante ciclo (evita chamadas duplicadas ao yfinance)
    - Cache de noticias durante ciclo (evita buscas duplicadas)
    - Tier determinado uma unica vez e reutilizado
    """

    def __init__(self, config: Dict[str, Any], market_data, news_scraper):
        """
        Inicializa o Buzz Factory.

        Args:
            config: Configuracoes do sistema
            market_data: Instancia do MarketDataCollector
            news_scraper: Instancia do NewsScraper
        """
        self.config = config
        self.market_data = market_data
        self.news_scraper = news_scraper

        # Cache de dados de mercado (limpo a cada ciclo de generate_daily_buzz)
        self._market_data_cache: Dict[str, Any] = {}

        # Cache de noticias (limpo a cada ciclo)
        self._news_cache: Dict[str, str] = {}

        # NewsAggregator para buscar noticias (lazy initialization)
        self._news_aggregator = None

    def _get_news_aggregator(self):
        """Lazy initialization do NewsAggregator."""
        if self._news_aggregator is None:
            from src.collectors.news_aggregator import NewsAggregator
            self._news_aggregator = NewsAggregator(self.config)
        return self._news_aggregator

    def _get_cached_stock_data(self, ticker: str) -> Optional[Any]:
        """
        Busca dados de mercado com cache.
        Evita chamadas duplicadas ao yfinance durante um ciclo.

        Args:
            ticker: Simbolo do ativo

        Returns:
            StockData ou None
        """
        if ticker in self._market_data_cache:
            return self._market_data_cache[ticker]

        data = self.market_data.get_stock_data(ticker)
        self._market_data_cache[ticker] = data
        return data

    def _determine_tier(self, market_cap: float) -> str:
        """
        Determina o tier baseado no market cap.
        Logica centralizada para evitar duplicacao.

        Args:
            market_cap: Market cap em dolares

        Returns:
            "tier1_large_cap", "tier2_mid_cap" ou "unknown"
        """
        tier_config = self.config.get("tiers", {})
        tier1_min = tier_config.get("tier1_large_cap", {}).get("min_market_cap", 4_000_000_000)
        tier2_min = tier_config.get("tier2_mid_cap", {}).get("min_market_cap", 800_000_000)

        if market_cap >= tier1_min:
            return "tier1_large_cap"
        elif market_cap >= tier2_min:
            return "tier2_mid_cap"
        else:
            return "unknown"

    async def _fetch_news_for_ticker(self, ticker: str) -> str:
        """
        Busca noticias para um ticker com cache.
        Retorna string formatada para news_content.

        Args:
            ticker: Simbolo do ativo

        Returns:
            String com noticias formatadas ou vazio
        """
        if ticker in self._news_cache:
            return self._news_cache[ticker]

        news_content = ""
        try:
            aggregator = self._get_news_aggregator()
            articles = await aggregator.get_gnews(ticker, max_results=3, fetch_full_content=False)

            if articles:
                parts = [f"Recent news for {ticker}:"]
                for art in articles[:3]:
                    title = art.get("title", "")
                    source = art.get("source", "")
                    if title:
                        parts.append(f"- [{source}] {title}")
                news_content = "\n".join(parts)
        except Exception as e:
            logger.debug(f"[NEWS] {ticker}: Erro ao buscar noticias - {e}")

        self._news_cache[ticker] = news_content
        return news_content

    def _clear_cycle_cache(self):
        """Limpa caches no inicio de cada ciclo de scan."""
        self._market_data_cache.clear()
        self._news_cache.clear()
        logger.debug("[CACHE] Caches limpos para novo ciclo")

    async def generate_daily_buzz(self, force_all: bool = False, max_candidates: int = 25) -> List[BuzzCandidate]:
        """
        Gera a lista de oportunidades do dia.

        Args:
            force_all: Se True, forca execucao de TODAS as fontes independente do horario (para testes)
            max_candidates: Numero maximo de candidatos a retornar (default: 25)

        Returns:
            Lista de candidatos ordenados por buzz_score (limitada a max_candidates)
        """
        # Limpa caches do ciclo anterior
        self._clear_cycle_cache()

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
        gap_candidates = await self._scan_gaps(force=force_all)
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

        # Limita ao máximo de candidatos
        total_found = len(candidates)
        candidates = candidates[:max_candidates]

        logger.info(f"Buzz Factory: {total_found} encontrados, top {len(candidates)} selecionados")
        return candidates

    async def _scan_watchlist(self) -> List[BuzzCandidate]:
        """
        Escaneia a watchlist fixa do arquivo config/watchlist.json.
        Processa TODOS os tiers (tier1_large_cap, tier2_mid_cap, etc).
        """
        candidates = []

        try:
            # Carregar watchlist do arquivo JSON
            watchlist_path = PROJECT_ROOT / "config" / "watchlist.json"

            if not watchlist_path.exists():
                logger.warning(f"Watchlist file not found: {watchlist_path}")
                return candidates

            with open(watchlist_path, "r") as f:
                watchlist_data = json.load(f)

            # Processar TODOS os tiers da watchlist
            all_tickers_with_tier = []
            for tier_name, tickers in watchlist_data.items():
                if isinstance(tickers, list):
                    for ticker in tickers:
                        all_tickers_with_tier.append((ticker, tier_name))

            total = len(all_tickers_with_tier)
            if total == 0:
                logger.warning("[WATCHLIST] Nenhum ticker encontrado na watchlist")
                return candidates

            logger.info(f"[WATCHLIST] Processando {total} tickers de {len(watchlist_data)} tiers...")

            # Verificar cada ticker
            for idx, (ticker, expected_tier) in enumerate(all_tickers_with_tier, 1):
                progress = (idx / total) * 100
                print(f"\r[WATCHLIST] {idx}/{total} ({progress:.0f}%) - {ticker}: processando...    ", end="", flush=True)

                try:
                    # Usar cache de market data
                    data = self._get_cached_stock_data(ticker)

                    if not data:
                        continue

                    # Obter market cap
                    market_cap_value = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0

                    # Verificar market cap minimo para o tier esperado
                    tier_config = self.config.get("tiers", {}).get(expected_tier, {})
                    min_market_cap = tier_config.get("min_market_cap", 0)

                    if market_cap_value < min_market_cap:
                        logger.debug(f"[WATCHLIST] {ticker}: Market cap ${market_cap_value/1e9:.2f}B < ${min_market_cap/1e9:.1f}B")
                        continue

                    # Determinar tier real baseado no market cap atual
                    actual_tier = self._determine_tier(market_cap_value)

                    # Buscar noticias para o ticker
                    news_content = await self._fetch_news_for_ticker(ticker)

                    # Score base varia por tier
                    base_score = 5.0 if actual_tier == "tier1_large_cap" else 4.0

                    candidates.append(BuzzCandidate(
                        ticker=ticker,
                        source="watchlist",
                        buzz_score=base_score,
                        reason=f"{actual_tier.replace('_', ' ').title()} watchlist (${market_cap_value/1e9:.1f}B cap)",
                        detected_at=datetime.now(),
                        tier=actual_tier,
                        market_cap=market_cap_value,
                        news_content=news_content
                    ))

                except Exception as e:
                    logger.debug(f"[WATCHLIST] {ticker}: Erro - {str(e)}")
                    continue

            print()  # Nova linha apos progress bar
            logger.info(f"[WATCHLIST] Completo: {len(candidates)}/{total} candidatos aprovados")

        except Exception as e:
            logger.error(f"Error scanning watchlist: {e}")

        return candidates

    async def _scan_volume_spikes(self) -> List[BuzzCandidate]:
        """
        Identifica ativos com volume anormal.

        Criterio: Volume PROJETADO > 2x media dos ultimos 20 dias
        (Projeta o volume atual para o dia completo baseado no tempo decorrido)
        """
        candidates = []

        try:
            phase0_config = self.config.get("phase0", {})
            volume_multiplier = phase0_config.get("volume_spike_multiplier", 2.0)
            min_dollar_volume = self.config.get("liquidity", {}).get("min_dollar_volume", 15_000_000)

            # Calcular fracao do dia de trading decorrida (mercado abre 9:30, fecha 16:00 = 6.5h)
            # NOTA: Horarios sao Eastern Time (ET), mas usamos local para simplificar
            # Fora do horario de mercado, yfinance retorna volume do dia anterior (completo)
            from datetime import time
            now = datetime.now()
            market_open = datetime.combine(now.date(), time(9, 30))
            market_close = datetime.combine(now.date(), time(16, 0))
            total_market_minutes = 6.5 * 60  # 390 minutos

            if now < market_open:
                # ANTES do mercado abrir: volume mostrado e do dia anterior (completo)
                # Nao faz sentido projetar - usar volume real vs media
                elapsed_fraction = 1.0
                logger.debug(f"[VOLUME] Pre-mercado: usando volume real (sem projecao)")
            elif now > market_close:
                # DEPOIS do mercado fechar: volume do dia esta completo
                elapsed_fraction = 1.0
                logger.debug(f"[VOLUME] Pos-mercado: usando volume real (dia completo)")
            else:
                # DURANTE o mercado: projetar volume baseado no tempo decorrido
                elapsed_minutes = (now - market_open).seconds / 60
                elapsed_fraction = max(0.1, min(1.0, elapsed_minutes / total_market_minutes))
                logger.debug(f"[VOLUME] Mercado aberto: {elapsed_fraction*100:.0f}% do dia, projetando volume")

            # Universo de tickers para escanear
            universe = self._get_scan_universe()
            total = len(universe)
            logger.info(f"[VOLUME SPIKES] Processando {total} tickers (>{volume_multiplier}x media, {elapsed_fraction*100:.0f}% do dia)...")

            scanned = 0
            for idx, ticker in enumerate(universe, 1):
                progress = (idx / total) * 100
                print(f"\r[VOLUME SPIKES] {idx}/{total} ({progress:.0f}%) - Escaneados: {scanned}, Spikes: {len(candidates)}    ", end="", flush=True)

                try:
                    # Usar cache de market data
                    data = self._get_cached_stock_data(ticker)

                    if not data:
                        continue

                    scanned += 1

                    # Calcular volume PROJETADO para o dia completo
                    if hasattr(data, 'volume') and hasattr(data, 'avg_volume'):
                        current_volume = data.volume
                        avg_volume = data.avg_volume
                        projected_volume = 0.0
                        volume_ratio = 0.0

                        if avg_volume > 0 and elapsed_fraction > 0:
                            # Projetar volume para o dia todo
                            projected_volume = current_volume / elapsed_fraction
                            volume_ratio = projected_volume / avg_volume

                        # Verificar criterios
                        if volume_ratio >= volume_multiplier:
                            # Verificar dollar volume (projetado)
                            projected_dollar_volume = projected_volume * data.price if hasattr(data, 'price') else 0

                            if projected_dollar_volume >= min_dollar_volume:
                                # Determinar tier usando metodo centralizado
                                market_cap_value = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0
                                tier = self._determine_tier(market_cap_value)

                                # Buscar noticias para o ticker
                                news_content = await self._fetch_news_for_ticker(ticker)

                                candidates.append(BuzzCandidate(
                                    ticker=ticker,
                                    source="volume_spike",
                                    buzz_score=7.0 + min(volume_ratio, 5.0),  # Score 7-12 baseado em volume
                                    reason=f"Volume spike {volume_ratio:.1f}x projetado (${projected_dollar_volume/1e6:.1f}M)",
                                    detected_at=datetime.now(),
                                    tier=tier,
                                    market_cap=market_cap_value,
                                    news_content=news_content
                                ))

                                logger.debug(f"{ticker}: Volume spike {volume_ratio:.1f}x detected (projected)")

                except Exception as e:
                    logger.debug(f"{ticker}: {str(e)}")
                    continue

            print()  # Nova linha apos progress bar
            logger.info(f"[VOLUME SPIKES] Completo: {len(candidates)} spikes de {scanned} tickers escaneados")

        except Exception as e:
            logger.error(f"Error in volume spike scan: {e}")

        return candidates

    def _get_scan_universe(self) -> List[str]:
        """
        Retorna universo de tickers para escanear.

        Universo amplo para descobrir oportunidades. O limite de candidatos
        que passam para a próxima fase é controlado em generate_daily_buzz().
        """
        return [
            # === USA - Big Tech ===
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            # === USA - Finance ===
            "JPM", "BAC", "GS",
            # === USA - Healthcare ===
            "JNJ", "UNH", "PFE", "LLY",
            # === USA - Consumer ===
            "WMT", "HD", "DIS", "NKE", "SBUX", "MCD",
            # === USA - Energy ===
            "XOM", "CVX", "COP",
            # === USA - Industrial ===
            "BA", "CAT", "GE",
            # === USA - Tech/Semiconductors ===
            "AMD", "INTC", "QCOM", "AVGO", "MU", "TSM",
            # === USA - Software ===
            "CRM", "ADBE", "ORCL",
            # === USA - Crypto/Volatil ===
            "COIN", "MSTR",
            # === USA - Popular ===
            "PLTR", "GME",
            # === BRASIL - ADRs (liquidez em USD) ===
            "PBR",   # Petrobras
            "VALE",  # Vale
            "ITUB",  # Itau
            "NU",    # Nubank
            "XP",    # XP Inc
            # === BRASIL - B3 (tickers validados) ===
            "PETR4.SA",  # Petrobras PN
            "VALE3.SA",  # Vale ON
            "ITUB4.SA",  # Itau PN
            "BBDC4.SA",  # Bradesco PN
            "WEGE3.SA",  # WEG ON
            "B3SA3.SA",  # B3 ON
            "RENT3.SA",  # Localiza ON
            "MGLU3.SA",  # Magazine Luiza ON
            "PRIO3.SA",  # PetroRio ON
        ]

    async def _scan_gaps(self, force: bool = False) -> List[BuzzCandidate]:
        """
        Identifica gaps significativos no pre-mercado ou abertura.

        Args:
            force: Se True, executa mesmo fora do horario (para testes)

        Criterio: Gap > 3% em relacao ao fechamento anterior
        """
        candidates = []

        try:
            phase0_config = self.config.get("phase0", {})
            gap_threshold = phase0_config.get("gap_threshold", 0.03)

            # Verificar se e horario de pre-mercado ou abertura (skip se force=True)
            if not force:
                now = datetime.now()
                market_open_time = datetime.strptime("09:30", "%H:%M").time()
                premarket_start = datetime.strptime("08:00", "%H:%M").time()

                # Executar apenas durante pre-mercado (08:00-09:30) ou nos primeiros 30min apos abertura
                is_premarket = premarket_start <= now.time() < market_open_time
                is_early_market = (now.time() >= market_open_time and
                                   (now - datetime.combine(now.date(), market_open_time)).seconds < 1800)

                if not (is_premarket or is_early_market):
                    logger.debug("Gap scan skipped: not in premarket/early market hours")
                    return candidates

            # Escanear universo de tickers
            universe = self._get_scan_universe()
            total = len(universe)
            logger.info(f"[GAP SCANNER] Processando {total} tickers (>{gap_threshold*100:.0f}% gap)...")

            scanned = 0
            for idx, ticker in enumerate(universe, 1):
                progress = (idx / total) * 100
                print(f"\r[GAP SCANNER] {idx}/{total} ({progress:.0f}%) - Escaneados: {scanned}, Gaps: {len(candidates)}    ", end="", flush=True)

                try:
                    # Usar cache de market data
                    data = self._get_cached_stock_data(ticker)

                    if not data:
                        continue

                    scanned += 1

                    # Calcular gap percentage
                    if hasattr(data, 'price') and hasattr(data, 'previous_close'):
                        if data.previous_close and data.previous_close > 0:
                            gap_pct = (data.price - data.previous_close) / data.previous_close

                            # Verificar se gap e significativo (positivo ou negativo)
                            if abs(gap_pct) >= gap_threshold:
                                gap_direction = "up" if gap_pct > 0 else "down"

                                # Determinar tier usando metodo centralizado
                                market_cap_value = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0
                                tier = self._determine_tier(market_cap_value)

                                # Buscar noticias para o ticker
                                news_content = await self._fetch_news_for_ticker(ticker)

                                candidates.append(BuzzCandidate(
                                    ticker=ticker,
                                    source="gap",
                                    buzz_score=8.0 + min(abs(gap_pct) * 10, 5.0),  # Score 8-13 baseado em gap
                                    reason=f"Gap {gap_direction} {gap_pct*100:.1f}% (${data.price:.2f} vs ${data.previous_close:.2f})",
                                    detected_at=datetime.now(),
                                    tier=tier,
                                    market_cap=market_cap_value,
                                    news_content=news_content
                                ))

                                logger.debug(f"{ticker}: Gap {gap_direction} {gap_pct*100:.1f}% detected")

                except Exception as e:
                    logger.debug(f"{ticker}: {str(e)}")
                    continue

            print()  # Nova linha apos progress bar
            logger.info(f"[GAP SCANNER] Completo: {len(candidates)} gaps de {scanned} tickers escaneados")

        except Exception as e:
            logger.error(f"Error in gap scan: {e}")

        return candidates

    async def _scan_news_catalysts(self) -> List[BuzzCandidate]:
        """
        Identifica ativos com catalisadores de noticias.

        Busca por: Earnings, M&A, FDA approvals, partnerships, etc.
        Usa NewsAggregator com Gemini NLP para extrair tickers.
        """
        candidates = []

        try:
            logger.info("Scanning news catalysts...")

            # Usar NewsAggregator via lazy initialization
            aggregator = self._get_news_aggregator()

            # Buscar noticias com catalisadores (usa keywords default expandidas do aggregator)
            catalyst_news = await aggregator.find_catalyst_news()

            # Converter NewsArticle para BuzzCandidate
            for article in catalyst_news:
                for ticker in article.tickers_mentioned:
                    # Verificar se ticker ja foi adicionado
                    if not any(c.ticker == ticker for c in candidates):
                        # Usar cache de market data
                        data = self._get_cached_stock_data(ticker)
                        market_cap_value = 0.0
                        tier = "unknown"

                        if data and hasattr(data, 'market_cap') and data.market_cap:
                            market_cap_value = data.market_cap
                            # Usar metodo centralizado para determinar tier
                            tier = self._determine_tier(market_cap_value)

                        # Construir conteudo da noticia para passar ao Screener/Judge
                        news_text = f"HEADLINE: {article.title}\n"
                        if article.summary:
                            news_text += f"SUMMARY: {article.summary}\n"
                        news_text += f"SOURCE: {article.source}"

                        candidates.append(BuzzCandidate(
                            ticker=ticker,
                            source="news_catalyst",
                            buzz_score=article.relevance_score,  # 8.0+ para catalysts
                            reason=f"Catalyst: {article.title[:80]}...",
                            detected_at=datetime.now(),
                            tier=tier,
                            market_cap=market_cap_value,
                            news_content=news_text  # Salvar conteudo para pipeline
                        ))

                        logger.debug(f"{ticker}: Catalyst news detected - {article.title[:50]}...")

            logger.info(f"News catalyst scan complete: {len(candidates)} candidates from {len(catalyst_news)} articles")

        except Exception as e:
            logger.error(f"Error in news catalyst scan: {e}")

        return candidates

    async def apply_filters(self, candidates: List[BuzzCandidate]) -> List[BuzzCandidate]:
        """
        Aplica filtros de market cap, liquidez, Friday blocking e earnings proximity.

        IMPORTANTE: Usa cache de market data para evitar chamadas duplicadas ao yfinance.
        O tier ja foi determinado nos scanners, so recalcula se estiver como "unknown".

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
        min_tier2_cap = self.config.get("tiers", {}).get("tier2_mid_cap", {}).get("min_market_cap", 800_000_000)

        # Verificar Friday blocking
        now = datetime.now()
        is_friday = now.weekday() == 4

        if is_friday and friday_block:
            logger.warning("[FILTER] FRIDAY BLOCKING ACTIVE - No new entries allowed")
            return []

        total = len(candidates)
        logger.info(f"[FILTER] Aplicando filtros em {total} candidatos...")

        for idx, candidate in enumerate(candidates, 1):
            ticker = candidate.ticker

            try:
                # Usar cache de market data (ja foi buscado nos scanners)
                data = self._get_cached_stock_data(ticker)

                if not data:
                    logger.debug(f"{ticker} rejected: no market data")
                    continue

                # 1. Market cap filtering
                market_cap = data.market_cap if hasattr(data, 'market_cap') and data.market_cap else 0.0
                if market_cap < min_tier2_cap:
                    logger.debug(f"{ticker} rejected: market cap ${market_cap/1e9:.2f}B < ${min_tier2_cap/1e9:.1f}B")
                    continue

                # 2. Atualizar tier APENAS se estiver como "unknown"
                # (evita recalcular o que ja foi determinado nos scanners)
                if candidate.tier == "unknown":
                    candidate.tier = self._determine_tier(market_cap)
                    logger.debug(f"{ticker}: tier atualizado para {candidate.tier}")

                # Atualizar market_cap se ainda nao foi definido
                if candidate.market_cap == 0.0:
                    candidate.market_cap = market_cap

                # 3. Verificar liquidez
                if not self.market_data.check_liquidity(ticker):
                    logger.debug(f"{ticker} rejected: low liquidity")
                    continue

                # 4. Verificar earnings proximity (< 5 dias)
                if earnings_checker.check_earnings_proximity(ticker):
                    logger.debug(f"{ticker} rejected: earnings within 5 days")
                    continue

                # 5. Verificar blacklist (se existir)
                # TODO: Implementar blacklist check se necessario

                # Candidato passou em todos os filtros
                filtered.append(candidate)
                logger.debug(f"{ticker} passed all filters (tier: {candidate.tier})")

            except Exception as e:
                logger.error(f"Error filtering {ticker}: {e}")
                continue

        # Log estatisticas de cache
        cache_hits = len([t for t in [c.ticker for c in candidates] if t in self._market_data_cache])
        logger.info(f"[FILTER] Cache hits: {cache_hits}/{total} ({cache_hits/total*100:.0f}% reuso)")
        logger.info(f"[FILTER] Completo: {len(filtered)}/{total} candidatos passaram")

        return filtered
