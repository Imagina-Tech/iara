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

    def __init__(self, config: Dict[str, Any], news_scraper, ai_gateway, state_manager):
        """
        Inicializa o sentinel.

        Args:
            config: Configurações
            news_scraper: Scraper de notícias
            ai_gateway: Gateway de IA
            state_manager: Gerenciador de estado
        """
        self.config = config
        self.news_scraper = news_scraper
        self.ai_gateway = ai_gateway
        self.state_manager = state_manager

        self._running = False
        self._check_interval = 300  # 5 minutos
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

        # Ação automática para críticos
        if alert.impact == NewsImpact.CRITICAL and alert.action_suggested == "EXIT_NOW":
            logger.critical(f"Notícia crítica para {alert.ticker}: {alert.headline}")
            # TODO: Considerar saída automática ou notificação urgente

    def _cleanup_seen_headlines(self) -> None:
        """Limpa headlines antigas."""
        cutoff = datetime.now() - timedelta(hours=24)
        self._seen_headlines = {
            headline: ts
            for headline, ts in self._seen_headlines.items()
            if ts > cutoff
        }

    def get_status(self) -> Dict[str, Any]:
        """Retorna status do sentinel."""
        return {
            "running": self._running,
            "check_interval": self._check_interval,
            "seen_headlines_count": len(self._seen_headlines)
        }
