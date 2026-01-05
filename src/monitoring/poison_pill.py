"""
POISON PILL SCANNER - Detector de Eventos Noturnos
Procura OPA/M&A, Gaps Overnight, Eventos Críticos
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Tipos de eventos detectados."""
    MERGER_ACQUISITION = "m&a"
    TENDER_OFFER = "tender_offer"  # OPA
    EARNINGS = "earnings"
    FDA_ACTION = "fda_action"
    SEC_INVESTIGATION = "sec_investigation"
    BANKRUPTCY = "bankruptcy"
    MAJOR_CONTRACT = "major_contract"
    INSIDER_TRADING = "insider_trading"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"


@dataclass
class PoisonPillEvent:
    """Evento detectado pelo scanner."""
    ticker: str
    event_type: EventType
    headline: str
    expected_impact: str  # "positive", "negative", "uncertain"
    magnitude: str  # "low", "medium", "high", "extreme"
    action_required: str
    source: str
    detected_at: datetime


class PoisonPillScanner:
    """
    Scanner noturno para eventos críticos.
    Roda após o fechamento do mercado.
    """

    def __init__(self, config: Dict[str, Any], news_scraper, ai_gateway, state_manager):
        """
        Inicializa o scanner.

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

        self._last_scan: Optional[datetime] = None
        self._detected_events: List[PoisonPillEvent] = []

        # Palavras-chave para detecção
        self._keywords = {
            EventType.MERGER_ACQUISITION: ["merger", "acquisition", "acquire", "takeover", "buyout", "m&a"],
            EventType.TENDER_OFFER: ["tender offer", "OPA", "offer to purchase", "compra de ações"],
            EventType.EARNINGS: ["earnings", "quarterly results", "revenue", "profit warning"],
            EventType.FDA_ACTION: ["FDA", "approval", "rejection", "clinical trial", "drug"],
            EventType.SEC_INVESTIGATION: ["SEC", "investigation", "probe", "subpoena", "fraud"],
            EventType.BANKRUPTCY: ["bankruptcy", "chapter 11", "chapter 7", "insolvency"],
            EventType.MAJOR_CONTRACT: ["contract", "deal", "partnership", "agreement"],
            EventType.INSIDER_TRADING: ["insider", "executive", "sell", "purchase", "filing"]
        }

    async def run_nightly_scan(self) -> List[PoisonPillEvent]:
        """
        Executa scan noturno completo.

        Returns:
            Lista de eventos detectados
        """
        logger.info("Iniciando Poison Pill Scan noturno...")
        self._detected_events = []

        positions = self.state_manager.get_open_positions()

        if not positions:
            logger.info("Nenhuma posição aberta para escanear")
            return []

        for position in positions:
            events = await self._scan_ticker(position.ticker)
            self._detected_events.extend(events)

        self._last_scan = datetime.now()

        if self._detected_events:
            logger.warning(f"Detectados {len(self._detected_events)} eventos de risco")
            for event in self._detected_events:
                logger.warning(f"  [{event.ticker}] {event.event_type.value}: {event.headline}")

        return self._detected_events

    async def _scan_ticker(self, ticker: str) -> List[PoisonPillEvent]:
        """
        Escaneia um ticker específico.

        Args:
            ticker: Símbolo do ativo

        Returns:
            Lista de eventos
        """
        events = []

        try:
            # Busca notícias das últimas 12 horas
            articles = await self.news_scraper.search_news(ticker, max_results=10)

            for article in articles:
                # Detecta tipo de evento
                event_type = self._detect_event_type(article.title, article.summary)

                if event_type:
                    # Analisa impacto com IA
                    analysis = await self._analyze_event(ticker, event_type, article)

                    if analysis:
                        events.append(PoisonPillEvent(
                            ticker=ticker,
                            event_type=event_type,
                            headline=article.title,
                            expected_impact=analysis.get("impact", "uncertain"),
                            magnitude=analysis.get("magnitude", "medium"),
                            action_required=analysis.get("action", "REVIEW"),
                            source=article.source,
                            detected_at=datetime.now()
                        ))

        except Exception as e:
            logger.error(f"Erro ao escanear {ticker}: {e}")

        return events

    def _detect_event_type(self, title: str, content: str) -> Optional[EventType]:
        """
        Detecta tipo de evento baseado em palavras-chave.

        Args:
            title: Título da notícia
            content: Conteúdo

        Returns:
            EventType ou None
        """
        text = f"{title} {content}".lower()

        for event_type, keywords in self._keywords.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    return event_type

        return None

    async def _analyze_event(self, ticker: str, event_type: EventType,
                             article) -> Optional[Dict]:
        """
        Analisa evento com IA.

        Args:
            ticker: Símbolo
            event_type: Tipo de evento
            article: Artigo

        Returns:
            Análise ou None
        """
        prompt = f"""
Analise este evento para {ticker}:

Tipo: {event_type.value}
Título: {article.title}
Resumo: {article.summary[:300]}

Responda em JSON:
{{
    "impact": "positive" | "negative" | "uncertain",
    "magnitude": "low" | "medium" | "high" | "extreme",
    "action": "HOLD" | "REVIEW" | "REDUCE" | "EXIT",
    "reason": "Explicação em 1 linha"
}}

Para M&A: considere se é o alvo (positivo) ou comprador (depende do preço)
Para OPA: geralmente positivo para o alvo
Para FDA: aprovação positiva, rejeição muito negativa
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
            logger.error(f"Erro na análise: {e}")

        return None

    async def check_pre_market_gaps(self, tickers: List[str]) -> List[PoisonPillEvent]:
        """
        Verifica gaps no pré-mercado.

        Args:
            tickers: Lista de tickers

        Returns:
            Eventos de gap
        """
        events = []

        # TODO: Implementar verificação de preços pré-mercado
        # Usar yfinance ou outra fonte para preços pre-market

        return events

    def get_critical_events(self) -> List[PoisonPillEvent]:
        """Retorna apenas eventos críticos (magnitude high/extreme)."""
        return [
            e for e in self._detected_events
            if e.magnitude in ["high", "extreme"]
        ]

    def should_run_scan(self) -> bool:
        """Verifica se deve rodar o scan (após market close)."""
        now = datetime.now()

        # Roda após 17:00 e antes de 08:00
        after_close = now.time() > time(17, 0)
        before_open = now.time() < time(8, 0)

        if not (after_close or before_open):
            return False

        # Não roda se já rodou nas últimas 6 horas
        if self._last_scan:
            hours_since_scan = (now - self._last_scan).seconds / 3600
            if hours_since_scan < 6:
                return False

        return True

    def get_status(self) -> Dict[str, Any]:
        """Retorna status do scanner."""
        return {
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "events_detected": len(self._detected_events),
            "critical_events": len(self.get_critical_events())
        }
