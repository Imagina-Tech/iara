"""
MARKET DATA COLLECTOR - Coleta de Dados de Mercado
Usa yfinance para OHLCV, MarketCap, Volume
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class StockData:
    """Dados completos de uma ação."""
    ticker: str
    price: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    avg_volume: int
    market_cap: float
    change_pct: float
    previous_close: Optional[float] = None
    beta: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class MarketDataCollector:
    """
    Coletor de dados de mercado usando yfinance.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o coletor.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self._cache: Dict[str, Any] = {}

    def get_stock_data(self, ticker: str) -> Optional[StockData]:
        """
        Obtém dados completos de uma ação.

        Args:
            ticker: Símbolo da ação

        Returns:
            StockData ou None se falhar
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.info if stock.info else {}
            hist = stock.history(period="1d")

            if hist.empty:
                logger.debug(f"{ticker}: Sem dados históricos")
                return None

            # Safely extract price data
            try:
                close_price = float(hist["Close"].iloc[-1])
                open_price = float(hist["Open"].iloc[-1])
                high_price = float(hist["High"].iloc[-1])
                low_price = float(hist["Low"].iloc[-1])
                volume = int(hist["Volume"].iloc[-1])
            except (KeyError, IndexError, ValueError) as e:
                logger.debug(f"{ticker}: Erro ao extrair dados OHLCV: {e}")
                return None

            # Get current price (prefer info, fallback to close)
            current_price = info.get("currentPrice") or info.get("regularMarketPrice") or close_price

            return StockData(
                ticker=ticker,
                price=current_price,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                avg_volume=info.get("averageVolume") or info.get("averageVolume10days") or 0,
                market_cap=info.get("marketCap") or 0,
                change_pct=info.get("regularMarketChangePercent") or 0,
                previous_close=info.get("previousClose") or info.get("regularMarketPreviousClose"),
                beta=info.get("beta"),
                sector=info.get("sector"),
                industry=info.get("industry")
            )

        except Exception as e:
            logger.debug(f"{ticker}: {str(e)}")
            return None

    def get_ohlcv(self, ticker: str, period: str = "1mo", interval: str = "1d") -> Optional[pd.DataFrame]:
        """
        Obtém dados OHLCV históricos.

        Args:
            ticker: Símbolo da ação
            period: Período (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Intervalo (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

        Returns:
            DataFrame com OHLCV ou None
        """
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)
            return df if not df.empty else None

        except Exception as e:
            logger.error(f"Erro ao obter OHLCV de {ticker}: {e}")
            return None

    def get_batch_data(self, tickers: List[str]) -> Dict[str, Optional[StockData]]:
        """
        Obtém dados de múltiplas ações em batch.

        Args:
            tickers: Lista de símbolos

        Returns:
            Dicionário ticker -> StockData
        """
        results = {}
        for ticker in tickers:
            results[ticker] = self.get_stock_data(ticker)
        return results

    def get_market_cap_tier(self, market_cap: float) -> str:
        """
        Determina o tier baseado no market cap.

        Args:
            market_cap: Capitalização de mercado

        Returns:
            "tier1_large_cap", "tier2_mid_cap" ou "tier3_small_cap"
        """
        tiers = self.config.get("tiers", {})

        tier1_min = tiers.get("tier1_large_cap", {}).get("min_market_cap", 10_000_000_000)
        tier2_min = tiers.get("tier2_mid_cap", {}).get("min_market_cap", 2_000_000_000)

        if market_cap >= tier1_min:
            return "tier1_large_cap"
        elif market_cap >= tier2_min:
            return "tier2_mid_cap"
        else:
            return "tier3_small_cap"

    def check_liquidity(self, ticker: str) -> bool:
        """
        Verifica se o ativo atende aos critérios de liquidez.

        Args:
            ticker: Símbolo da ação

        Returns:
            True se passar nos filtros de liquidez
        """
        data = self.get_stock_data(ticker)
        if not data:
            return False

        liquidity = self.config.get("liquidity", {})
        min_volume = liquidity.get("min_avg_volume", 500000)
        min_dollar_volume = liquidity.get("min_dollar_volume", 5000000)

        dollar_volume = data.avg_volume * data.price

        return data.avg_volume >= min_volume and dollar_volume >= min_dollar_volume
