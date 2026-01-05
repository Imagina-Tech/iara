"""
SENTINEL - IA Monitor de Notícias
Monitora notícias de posições abertas em tempo real
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class NewsImpact(Enum):
    """Impacto de notícia."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    CRITICAL = "critical"


@dataclass
class NewsAlert:
    """Alerta de notícia."""
    ticker: str
    headline: str
    impact: NewsImpact
    summary: str
    action_suggested: str
    confidence: float
    source: str
    timestamp: datetime


class Sentinel:
    """
    Sentinela de notícias usando IA.
    Monitora notícias de posições abertas.
    """

    def __init__(self, config: Dict[str, Any], news_scraper, ai_gateway, state_manager,
                 judge=None, order_manager=None):
        """
        Inicializa o sentinel.

        Args:
            config: Configurações
            news_scraper: Scraper de notícias
            ai_gateway: Gateway de IA
            state_manager: Gerenciador de estado
            judge: Judge instance (WS6 - para exit decisions)
            order_manager: Order manager (WS6 - para trailing stops)
        """
        self.config = config
        self.news_scraper = news_scraper
        self.ai_gateway = ai_gateway
        self.state_manager = state_manager
        self.judge = judge  # WS6
        self.order_manager = order_manager  # WS6

        self.phase5_config = config.get("phase5", {})
        self._running = False
        self._check_interval = self.phase5_config.get("sentinel_interval", 300)  # 5 minutos
        self._seen_headlines: Dict[str, datetime] = {}
        self._alert_handlers: List = []

    def add_alert_handler(self, handler) -> None:
        """Adiciona handler de alertas."""
        self._alert_handlers.append(handler)

    async def start(self) -> None:
        """Inicia o sentinel."""
        logger.info("Iniciando Sentinel...")
        self._running = True

        while self._running:
            try:
                await self._scan_news()
                await asyncio.sleep(self._check_interval)
            except Exception as e:
                logger.error(f"Erro no sentinel: {e}")
                await asyncio.sleep(30)

    async def stop(self) -> None:
        """Para o sentinel."""
        logger.info("Parando Sentinel...")
        self._running = False

    async def _scan_news(self) -> None:
        """Escaneia notícias das posições abertas."""
        positions = self.state_manager.get_open_positions()

        for position in positions:
            try:
                alerts = await self._check_ticker_news(position.ticker)

                for alert in alerts:
                    await self._handle_alert(alert)

            except Exception as e:
                logger.error(f"Erro ao verificar notícias de {position.ticker}: {e}")

    async def _check_ticker_news(self, ticker: str) -> List[NewsAlert]:
        """
        Verifica notícias de um ticker.

        Args:
            ticker: Símbolo do ativo

        Returns:
            Lista de alertas
        """
        alerts = []

        # Busca notícias recentes
        articles = await self.news_scraper.search_news(ticker, max_results=5)

        for article in articles:
            # Verifica se já vimos essa headline
            if article.title in self._seen_headlines:
                continue

            # Marca como vista
            self._seen_headlines[article.title] = datetime.now()

            # Analisa com IA
            analysis = await self._analyze_news(ticker, article.title, article.summary)

            if analysis and analysis.get("impact") in ["negative", "critical"]:
                alerts.append(NewsAlert(
                    ticker=ticker,
                    headline=article.title,
                    impact=NewsImpact(analysis.get("impact", "neutral")),
                    summary=analysis.get("summary", ""),
                    action_suggested=analysis.get("action", "MONITOR"),
                    confidence=analysis.get("confidence", 0.5),
                    source=article.source,
                    timestamp=datetime.now()
                ))

        # Limpa headlines antigas (mais de 24h)
        self._cleanup_seen_headlines()

        return alerts

    async def _analyze_news(self, ticker: str, headline: str, content: str) -> Optional[Dict]:
        """
        Analisa notícia com IA.

        Args:
            ticker: Símbolo do ativo
            headline: Título
            content: Conteúdo

        Returns:
            Análise ou None
        """
        prompt = f"""
Analise esta notícia sobre {ticker} e determine o impacto no preço:

Título: {headline}
Conteúdo: {content[:500]}

Responda em JSON:
{{
    "impact": "positive" | "neutral" | "negative" | "critical",
    "summary": "Resumo em 1 linha",
    "action": "HOLD" | "MONITOR" | "CONSIDER_EXIT" | "EXIT_NOW",
    "confidence": 0.0 a 1.0
}}

Critérios para "critical":
- M&A negativa, investigação SEC, fraude, falência, recall massivo
"""

        try:
            response = await self.ai_gateway.complete(
                prompt=prompt,
                temperature=0.2,
                max_tokens=300
            )

            if response.success and response.parsed_json:
                return response.parsed_json

        except Exception as e:
            logger.error(f"Erro na análise de notícia: {e}")

        return None

    async def _handle_alert(self, alert: NewsAlert) -> None:
        """Processa alerta de notícia."""
        level = "CRITICAL" if alert.impact == NewsImpact.CRITICAL else "WARNING"
        logger.warning(f"[{level}] {alert.ticker}: {alert.headline}")
        logger.info(f"  Impacto: {alert.impact.value} | Ação: {alert.action_suggested}")

        # Notifica handlers
        for handler in self._alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Erro no handler: {e}")

        # WS6: Ação automática para críticos - chamar Judge
        if alert.impact in [NewsImpact.NEGATIVE, NewsImpact.CRITICAL]:
            # Find position
            positions = self.state_manager.get_open_positions()
            position = next((p for p in positions if p.ticker == alert.ticker), None)

            if position:
                await self.call_judge_for_exit(position, alert)

    def _cleanup_seen_headlines(self) -> None:
        """Limpa headlines antigas."""
        cutoff = datetime.now() - timedelta(hours=24)
        self._seen_headlines = {
            headline: ts
            for headline, ts in self._seen_headlines.items()
            if ts > cutoff
        }

    async def check_friday_breakeven(self) -> None:
        """
        WS6: Friday afternoon breakeven logic.
        Se Friday após 14:00, mover stops lucrativas para breakeven.
        """
        now = datetime.now()

        # Check if Friday (weekday == 4) and after 14:00
        if now.weekday() != 4:
            return

        if now.hour < 14:
            return

        logger.info("Friday afternoon: Moving profitable positions to breakeven")

        positions = self.state_manager.get_open_positions()

        for position in positions:
            # Check if position is profitable
            current_price = position.current_price if position.current_price > 0 else position.entry_price
            is_profitable = (
                (position.direction == "LONG" and current_price > position.entry_price) or
                (position.direction == "SHORT" and current_price < position.entry_price)
            )

            if is_profitable and self.order_manager:
                # Move stop to breakeven (+0.1% buffer)
                breakeven_price = position.entry_price * 1.001 if position.direction == "LONG" else position.entry_price * 0.999

                logger.info(f"Friday breakeven: Moving {position.ticker} stop to ${breakeven_price:.2f}")

                # Update stop order
                # TODO: Implement order_manager.update_stop_order()

    async def update_trailing_stops(self) -> None:
        """
        WS6: Update trailing stops for profitable positions.
        Trailing stop = Current price - 2*ATR
        """
        positions = self.state_manager.get_open_positions()

        for position in positions:
            try:
                # Fetch current price and ATR
                import yfinance as yf
                ticker_obj = yf.Ticker(position.ticker)
                hist = ticker_obj.history(period="20d")

                if hist.empty:
                    continue

                current_price = hist["Close"].iloc[-1]

                # Calculate ATR
                import pandas_ta as ta
                atr_series = ta.atr(hist["High"], hist["Low"], hist["Close"], length=14)
                if atr_series is None or atr_series.empty:
                    continue

                atr = atr_series.iloc[-1]

                # Calculate trailing stop
                if position.direction == "LONG":
                    trailing_stop = current_price - (2 * atr)

                    # Only update if trailing stop > current stop (tighten only)
                    if trailing_stop > position.stop_loss:
                        logger.info(f"Trailing stop update: {position.ticker} ${position.stop_loss:.2f} → ${trailing_stop:.2f}")

                        # Update position in state manager
                        position.stop_loss = round(trailing_stop, 2)

                        # Update stop order at broker
                        if self.order_manager:
                            # TODO: Implement order_manager.update_stop_order()
                            pass

                else:  # SHORT
                    trailing_stop = current_price + (2 * atr)

                    # Only update if trailing stop < current stop (tighten only)
                    if trailing_stop < position.stop_loss:
                        logger.info(f"Trailing stop update: {position.ticker} ${position.stop_loss:.2f} → ${trailing_stop:.2f}")

                        position.stop_loss = round(trailing_stop, 2)

                        if self.order_manager:
                            # TODO: Implement order_manager.update_stop_order()
                            pass

            except Exception as e:
                logger.error(f"Error updating trailing stop for {position.ticker}: {e}")

    async def call_judge_for_exit(self, position, news_alert: NewsAlert) -> None:
        """
        WS6: Chama Judge para decisão de saída baseada em news negativo.

        Args:
            position: Posição aberta
            news_alert: Alert de notícia negativa
        """
        if not self.judge:
            logger.warning("Judge not available for exit decision")
            return

        try:
            logger.info(f"Calling Judge for exit decision on {position.ticker} due to news: {news_alert.headline[:50]}...")

            # Prepare data for Judge
            # TODO: Fetch full market/technical data
            market_data = {"ticker": position.ticker, "price": position.current_price}
            technical_data = {}
            macro_data = {}
            correlation_data = {}
            news_details = f"NEGATIVE NEWS: {news_alert.headline}\n{news_alert.summary}"

            # Call Judge (simplified - não é full judge, apenas exit recommendation)
            # Poderia ter um método judge.get_exit_recommendation() específico
            logger.info(f"Judge recommendation needed for {position.ticker} - news impact: {news_alert.impact.value}")

            # Ação baseada na severidade
            if news_alert.impact == NewsImpact.CRITICAL and news_alert.action_suggested == "EXIT_NOW":
                logger.critical(f"CRITICAL NEWS: Closing {position.ticker} immediately")
                # TODO: order_manager.close_position_at_market(position)

        except Exception as e:
            logger.error(f"Error calling Judge for exit: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Retorna status do sentinel."""
        return {
            "running": self._running,
            "check_interval": self._check_interval,
            "seen_headlines_count": len(self._seen_headlines)
        }
