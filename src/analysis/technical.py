"""
TECHNICAL ANALYZER - Análise Técnica
Usa pandas_ta: RSI, ATR, SuperTrend, Volume Profile
"""

import logging
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


@dataclass
class TechnicalSignals:
    """Sinais técnicos consolidados."""
    ticker: str
    rsi: float
    rsi_signal: str  # "oversold", "overbought", "neutral"
    atr: float
    atr_percent: float
    supertrend: float
    supertrend_direction: str  # "bullish", "bearish"
    volume_ratio: float
    support: float
    resistance: float
    trend: str  # "uptrend", "downtrend", "sideways"
    # WS2 additions
    ema_20: float = 0.0
    ema_50: float = 0.0
    ema_trend: str = "neutral"
    avg_volume_20d: float = 0.0
    dollar_volume: float = 0.0


class TechnicalAnalyzer:
    """
    Analisador técnico usando pandas_ta.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o analisador.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.tech_config = config.get("technical", {})

    def analyze(self, df: pd.DataFrame, ticker: str) -> Optional[TechnicalSignals]:
        """
        Realiza análise técnica completa.

        Args:
            df: DataFrame com OHLCV
            ticker: Símbolo do ativo

        Returns:
            TechnicalSignals ou None
        """
        if df is None or df.empty or len(df) < 20:
            logger.warning(f"Dados insuficientes para análise de {ticker}")
            return None

        try:
            # RSI
            rsi_period = self.tech_config.get("rsi_period", 14)
            df["RSI"] = ta.rsi(df["Close"], length=rsi_period)
            rsi_value = df["RSI"].iloc[-1]

            # ATR
            atr_period = self.tech_config.get("atr_period", 14)
            df["ATR"] = ta.atr(df["High"], df["Low"], df["Close"], length=atr_period)
            atr_value = df["ATR"].iloc[-1]
            atr_percent = (atr_value / df["Close"].iloc[-1]) * 100

            # SuperTrend
            st_period = self.tech_config.get("supertrend_period", 10)
            st_mult = self.tech_config.get("supertrend_multiplier", 3.0)
            supertrend = ta.supertrend(df["High"], df["Low"], df["Close"],
                                       length=st_period, multiplier=st_mult)

            st_col = f"SUPERT_{st_period}_{st_mult}"
            std_col = f"SUPERTd_{st_period}_{st_mult}"

            st_value = supertrend[st_col].iloc[-1] if st_col in supertrend.columns else 0
            st_direction = "bullish" if supertrend[std_col].iloc[-1] == 1 else "bearish"

            # Volume Ratio
            avg_volume = df["Volume"].rolling(20).mean().iloc[-1]
            current_volume = df["Volume"].iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

            # EMA (20 e 50 períodos)
            ema_20 = df["Close"].ewm(span=20, adjust=False).mean().iloc[-1] if len(df) >= 20 else 0
            ema_50 = df["Close"].ewm(span=50, adjust=False).mean().iloc[-1] if len(df) >= 50 else 0
            ema_trend = "bullish" if ema_20 > ema_50 else "bearish" if ema_50 > 0 else "neutral"

            # Dollar volume
            dollar_volume = current_volume * df["Close"].iloc[-1]

            # Suporte e Resistência (pivots simples)
            support, resistance = self._calculate_pivot_levels(df)

            # Tendência
            trend = self._determine_trend(df)

            return TechnicalSignals(
                ticker=ticker,
                rsi=rsi_value,
                rsi_signal=self._get_rsi_signal(rsi_value),
                atr=atr_value,
                atr_percent=atr_percent,
                supertrend=st_value,
                supertrend_direction=st_direction,
                volume_ratio=volume_ratio,
                support=support,
                resistance=resistance,
                trend=trend,
                ema_20=ema_20,
                ema_50=ema_50,
                ema_trend=ema_trend,
                avg_volume_20d=avg_volume,
                dollar_volume=dollar_volume
            )

        except Exception as e:
            logger.error(f"Erro na análise técnica de {ticker}: {e}")
            return None

    def _get_rsi_signal(self, rsi: float) -> str:
        """Interpreta o RSI."""
        if rsi < 30:
            return "oversold"
        elif rsi > 70:
            return "overbought"
        else:
            return "neutral"

    def _calculate_pivot_levels(self, df: pd.DataFrame) -> Tuple[float, float]:
        """
        Calcula níveis de suporte e resistência.

        Returns:
            Tuple (support, resistance)
        """
        high = df["High"].iloc[-20:].max()
        low = df["Low"].iloc[-20:].min()
        close = df["Close"].iloc[-1]

        pivot = (high + low + close) / 3
        support = (2 * pivot) - high
        resistance = (2 * pivot) - low

        return support, resistance

    def _determine_trend(self, df: pd.DataFrame) -> str:
        """Determina a tendência atual."""
        if len(df) < 50:
            return "sideways"

        sma_20 = df["Close"].rolling(20).mean().iloc[-1]
        sma_50 = df["Close"].rolling(50).mean().iloc[-1]
        current_price = df["Close"].iloc[-1]

        if current_price > sma_20 > sma_50:
            return "uptrend"
        elif current_price < sma_20 < sma_50:
            return "downtrend"
        else:
            return "sideways"

    def calculate_stop_levels(self, entry_price: float, atr: float,
                              direction: str, risk_multiplier: float = 2.0) -> Dict[str, float]:
        """
        Calcula níveis de stop e take profit.

        Args:
            entry_price: Preço de entrada
            atr: ATR atual
            direction: "LONG" ou "SHORT"
            risk_multiplier: Multiplicador para TP

        Returns:
            Dict com stop_loss, take_profit_1, take_profit_2
        """
        if direction == "LONG":
            stop_loss = entry_price - (1.5 * atr)
            take_profit_1 = entry_price + (risk_multiplier * atr)
            take_profit_2 = entry_price + (risk_multiplier * 1.5 * atr)
        else:  # SHORT
            stop_loss = entry_price + (1.5 * atr)
            take_profit_1 = entry_price - (risk_multiplier * atr)
            take_profit_2 = entry_price - (risk_multiplier * 1.5 * atr)

        return {
            "stop_loss": round(stop_loss, 2),
            "take_profit_1": round(take_profit_1, 2),
            "take_profit_2": round(take_profit_2, 2),
            "risk_reward_ratio": risk_multiplier
        }
