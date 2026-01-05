"""
MACRO DATA COLLECTOR - Dados Macroeconômicos
Puxa VIX, SPY e Calendário Econômico
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

import yfinance as yf

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Regime de mercado baseado no VIX."""
    LOW_VOL = "low_volatility"      # VIX < 15
    NORMAL = "normal"               # 15 <= VIX < 20
    ELEVATED = "elevated"           # 20 <= VIX < 25
    HIGH_VOL = "high_volatility"    # 25 <= VIX < 30
    EXTREME = "extreme"             # VIX >= 30


@dataclass
class MacroSnapshot:
    """Snapshot de dados macro."""
    timestamp: datetime
    vix: float
    vix_regime: MarketRegime
    spy_price: float
    spy_change_pct: float
    spy_trend: str  # "bullish", "bearish", "neutral"
    qqq_price: float
    qqq_change_pct: float
    dxy_price: float  # Dollar Index
    us10y_yield: float  # Treasury 10Y


@dataclass
class EconomicEvent:
    """Evento do calendário econômico."""
    date: date
    time: str
    event: str
    importance: str  # "high", "medium", "low"
    forecast: Optional[str]
    previous: Optional[str]


class MacroDataCollector:
    """
    Coletor de dados macroeconômicos.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o coletor macro.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self._last_snapshot: Optional[MacroSnapshot] = None

    def get_macro_snapshot(self) -> MacroSnapshot:
        """
        Obtém snapshot atual de dados macro.

        Returns:
            MacroSnapshot com dados atuais
        """
        try:
            # VIX
            vix_data = yf.Ticker("^VIX")
            vix_price = vix_data.info.get("regularMarketPrice", 0)

            # SPY
            spy_data = yf.Ticker("SPY")
            spy_info = spy_data.info
            spy_price = spy_info.get("regularMarketPrice", 0)
            spy_change = spy_info.get("regularMarketChangePercent", 0)

            # QQQ
            qqq_data = yf.Ticker("QQQ")
            qqq_info = qqq_data.info
            qqq_price = qqq_info.get("regularMarketPrice", 0)
            qqq_change = qqq_info.get("regularMarketChangePercent", 0)

            # DXY (Dollar Index)
            dxy_data = yf.Ticker("DX-Y.NYB")
            dxy_price = dxy_data.info.get("regularMarketPrice", 0)

            # 10Y Treasury
            tny_data = yf.Ticker("^TNX")
            tny_yield = tny_data.info.get("regularMarketPrice", 0)

            snapshot = MacroSnapshot(
                timestamp=datetime.now(),
                vix=vix_price,
                vix_regime=self._get_vix_regime(vix_price),
                spy_price=spy_price,
                spy_change_pct=spy_change,
                spy_trend=self._get_trend(spy_change),
                qqq_price=qqq_price,
                qqq_change_pct=qqq_change,
                dxy_price=dxy_price,
                us10y_yield=tny_yield
            )

            self._last_snapshot = snapshot
            return snapshot

        except Exception as e:
            logger.error(f"Erro ao obter dados macro: {e}")
            if self._last_snapshot:
                return self._last_snapshot
            raise

    def _get_vix_regime(self, vix: float) -> MarketRegime:
        """Determina o regime de mercado baseado no VIX."""
        if vix < 15:
            return MarketRegime.LOW_VOL
        elif vix < 20:
            return MarketRegime.NORMAL
        elif vix < 25:
            return MarketRegime.ELEVATED
        elif vix < 30:
            return MarketRegime.HIGH_VOL
        else:
            return MarketRegime.EXTREME

    def _get_trend(self, change_pct: float) -> str:
        """Determina a tendência baseada na variação."""
        if change_pct > 0.5:
            return "bullish"
        elif change_pct < -0.5:
            return "bearish"
        else:
            return "neutral"

    def is_high_risk_environment(self) -> bool:
        """
        Verifica se o ambiente é de alto risco.

        Returns:
            True se VIX >= 30 ou outras condições de risco
        """
        snapshot = self.get_macro_snapshot()
        return snapshot.vix_regime in [MarketRegime.HIGH_VOL, MarketRegime.EXTREME]

    async def get_economic_calendar(self, days_ahead: int = 7) -> List[EconomicEvent]:
        """
        Obtém calendário econômico.

        Args:
            days_ahead: Dias para buscar eventos

        Returns:
            Lista de eventos econômicos
        """
        # TODO: Integrar com API de calendário econômico
        # Sugestões: Trading Economics, Investing.com API
        logger.info(f"Buscando calendário econômico para {days_ahead} dias...")
        return []

    def should_reduce_exposure(self) -> bool:
        """
        Verifica se deve reduzir exposição baseado em macro.

        Returns:
            True se condições macro sugerem redução de risco
        """
        snapshot = self.get_macro_snapshot()

        # Reduz se VIX elevado
        if snapshot.vix >= 25:
            return True

        # Reduz se SPY em queda forte
        if snapshot.spy_change_pct < -2.0:
            return True

        return False
