"""
EARNINGS CHECKER - Verificador de Earnings Proximity
Bloqueia entradas se earnings report estiver próximo (< 5 dias)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


class EarningsChecker:
    """
    Verifica proximidade de earnings reports para evitar entradas em alta volatilidade.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o earnings checker.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.phase0_config = config.get("phase0", {})
        self.proximity_days: int = self.phase0_config.get("earnings_proximity_days", 5)

        # Cache de earnings (evitar múltiplas consultas)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_expiry = timedelta(hours=24)

    def check_earnings_proximity(
        self,
        ticker: str,
        days: Optional[int] = None
    ) -> bool:
        """
        Verifica se earnings está próximo.

        Args:
            ticker: Ticker do ativo
            days: Número de dias para verificar (default: config)

        Returns:
            True se earnings está dentro da janela de proximidade
        """
        if days is None:
            days = self.proximity_days

        try:
            # Verificar cache
            cached_data = self._get_cached_earnings(ticker)

            if cached_data:
                next_earnings = cached_data.get("next_earnings_date")
            else:
                # Buscar earnings date via yfinance
                next_earnings = self._fetch_earnings_date(ticker)

                # Armazenar em cache
                self._cache[ticker] = {
                    "next_earnings_date": next_earnings,
                    "cached_at": datetime.now()
                }

            if next_earnings is None:
                # Sem data de earnings disponível - permitir entrada
                logger.debug(f"{ticker}: No earnings date available, allowing entry")
                return False

            # Calcular dias até earnings
            days_until = (next_earnings - datetime.now()).days

            if 0 <= days_until <= days:
                logger.info(f"{ticker}: Earnings in {days_until} days - BLOCKING ENTRY")
                return True

            logger.debug(f"{ticker}: Earnings in {days_until} days - OK")
            return False

        except Exception as e:
            logger.error(f"Error checking earnings for {ticker}: {e}")
            # Em caso de erro, permitir entrada (fail-safe)
            return False

    def _get_cached_earnings(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Retorna earnings em cache se ainda válido.

        Args:
            ticker: Ticker do ativo

        Returns:
            Dict com earnings data ou None se cache expirado/inexistente
        """
        if ticker not in self._cache:
            return None

        cached = self._cache[ticker]
        cached_at = cached.get("cached_at")

        if cached_at and (datetime.now() - cached_at) < self._cache_expiry:
            return cached

        # Cache expirado
        del self._cache[ticker]
        return None

    def _fetch_earnings_date(self, ticker: str) -> Optional[datetime]:
        """
        Busca próxima data de earnings via yfinance.

        Args:
            ticker: Ticker do ativo

        Returns:
            Datetime do próximo earnings ou None se não disponível
        """
        try:
            stock = yf.Ticker(ticker)

            # Tentar obter calendar
            calendar = stock.calendar

            if calendar is None or (isinstance(calendar, pd.DataFrame) and calendar.empty):
                logger.debug(f"{ticker}: No calendar data available")
                return None

            # yfinance retorna DataFrame com earnings dates
            # Formato pode variar dependendo da versão
            if isinstance(calendar, dict):
                # Formato dict
                earnings_date = calendar.get("Earnings Date")

                if earnings_date is not None:
                    # Pode ser uma lista ou um valor único
                    if isinstance(earnings_date, list) and len(earnings_date) > 0:
                        # Pegar a primeira data (próxima)
                        next_date = earnings_date[0]
                    else:
                        next_date = earnings_date

                    # Converter para datetime se necessário
                    if isinstance(next_date, str):
                        # Parsing de string (formato pode variar)
                        try:
                            return datetime.strptime(next_date, "%Y-%m-%d")
                        except:
                            # Tentar outros formatos
                            from dateutil import parser
                            return parser.parse(next_date)
                    elif isinstance(next_date, datetime):
                        return next_date
                    elif hasattr(next_date, 'to_pydatetime'):
                        # pandas Timestamp
                        return next_date.to_pydatetime()
                    else:
                        return None

            # Tentar info alternativo
            info = stock.info

            if info and "earningsDate" in info:
                earnings_timestamp = info["earningsDate"]

                if earnings_timestamp:
                    # Pode ser timestamp unix
                    if isinstance(earnings_timestamp, int):
                        return datetime.fromtimestamp(earnings_timestamp)
                    elif isinstance(earnings_timestamp, str):
                        from dateutil import parser
                        return parser.parse(earnings_timestamp)

            logger.debug(f"{ticker}: No earnings date found in calendar or info")
            return None

        except Exception as e:
            logger.error(f"Error fetching earnings date for {ticker}: {e}")
            return None

    def get_earnings_info(self, ticker: str) -> Dict[str, Any]:
        """
        Retorna informações completas sobre earnings.

        Args:
            ticker: Ticker do ativo

        Returns:
            Dict com info de earnings
        """
        result = {
            "ticker": ticker,
            "next_earnings_date": None,
            "days_until": None,
            "is_blocked": False,
            "checked_at": datetime.now().isoformat()
        }

        try:
            next_earnings = self._fetch_earnings_date(ticker)

            if next_earnings:
                days_until = (next_earnings - datetime.now()).days

                result["next_earnings_date"] = next_earnings.isoformat()
                result["days_until"] = days_until
                result["is_blocked"] = (0 <= days_until <= self.proximity_days)

        except Exception as e:
            logger.error(f"Error getting earnings info for {ticker}: {e}")
            result["error"] = str(e)

        return result

    def clear_cache(self, ticker: Optional[str] = None):
        """
        Limpa cache de earnings.

        Args:
            ticker: Ticker específico ou None para limpar tudo
        """
        if ticker:
            if ticker in self._cache:
                del self._cache[ticker]
                logger.debug(f"Cleared earnings cache for {ticker}")
        else:
            self._cache.clear()
            logger.debug("Cleared all earnings cache")
