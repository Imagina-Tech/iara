"""
RISK MATH - Cálculos de Risco (FASE 2)
Beta, Volatilidade e Kelly Criterion
"""

import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Métricas de risco de um ativo."""
    ticker: str
    beta: float
    volatility_20d: float
    volatility_60d: float
    sharpe_ratio: float
    max_drawdown: float
    var_95: float  # Value at Risk 95%
    cvar_95: float  # Conditional VaR


class RiskCalculator:
    """
    Calculadora de métricas de risco.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa a calculadora.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.risk_config = config.get("risk", {})
        self.risk_free_rate = 0.05  # 5% ao ano

    def calculate_risk_metrics(self, df: pd.DataFrame, benchmark_df: pd.DataFrame,
                               ticker: str) -> Optional[RiskMetrics]:
        """
        Calcula métricas de risco completas.

        Args:
            df: DataFrame do ativo com OHLCV
            benchmark_df: DataFrame do benchmark (SPY)
            ticker: Símbolo do ativo

        Returns:
            RiskMetrics ou None
        """
        if df is None or df.empty or len(df) < 60:
            return None

        try:
            returns = df["Close"].pct_change().dropna()

            # Beta
            beta = self._calculate_beta(df, benchmark_df)

            # Volatilidade
            vol_20d = returns.tail(20).std() * np.sqrt(252) * 100
            vol_60d = returns.tail(60).std() * np.sqrt(252) * 100

            # Sharpe Ratio
            excess_returns = returns.mean() * 252 - self.risk_free_rate
            sharpe = excess_returns / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

            # Max Drawdown
            max_dd = self._calculate_max_drawdown(df["Close"])

            # VaR e CVaR
            var_95 = self._calculate_var(returns, 0.95)
            cvar_95 = self._calculate_cvar(returns, 0.95)

            return RiskMetrics(
                ticker=ticker,
                beta=beta,
                volatility_20d=vol_20d,
                volatility_60d=vol_60d,
                sharpe_ratio=sharpe,
                max_drawdown=max_dd,
                var_95=var_95,
                cvar_95=cvar_95
            )

        except Exception as e:
            logger.error(f"Erro ao calcular métricas de risco de {ticker}: {e}")
            return None

    def _calculate_beta(self, asset_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> float:
        """Calcula o Beta do ativo em relação ao benchmark."""
        try:
            asset_returns = asset_df["Close"].pct_change().dropna()
            bench_returns = benchmark_df["Close"].pct_change().dropna()

            # Alinha as séries
            aligned = pd.concat([asset_returns, bench_returns], axis=1).dropna()
            if len(aligned) < 20:
                return 1.0

            covariance = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
            variance = aligned.iloc[:, 1].var()

            return covariance / variance if variance > 0 else 1.0

        except Exception:
            return 1.0

    def _calculate_max_drawdown(self, prices: pd.Series) -> float:
        """Calcula o drawdown máximo."""
        peak = prices.expanding(min_periods=1).max()
        drawdown = (prices - peak) / peak
        return abs(drawdown.min()) * 100

    def _calculate_var(self, returns: pd.Series, confidence: float) -> float:
        """Calcula Value at Risk."""
        return abs(np.percentile(returns, (1 - confidence) * 100)) * 100

    def _calculate_cvar(self, returns: pd.Series, confidence: float) -> float:
        """Calcula Conditional VaR (Expected Shortfall)."""
        var = np.percentile(returns, (1 - confidence) * 100)
        cvar = returns[returns <= var].mean()
        return abs(cvar) * 100 if not np.isnan(cvar) else 0

    def calculate_position_risk(self, entry_price: float, stop_loss: float,
                                position_size: int) -> Dict[str, float]:
        """
        Calcula o risco de uma posição.

        Args:
            entry_price: Preço de entrada
            stop_loss: Preço do stop loss
            position_size: Quantidade de ações

        Returns:
            Dict com métricas de risco da posição
        """
        risk_per_share = abs(entry_price - stop_loss)
        total_risk = risk_per_share * position_size
        risk_percent = (risk_per_share / entry_price) * 100

        return {
            "risk_per_share": round(risk_per_share, 2),
            "total_risk": round(total_risk, 2),
            "risk_percent": round(risk_percent, 2),
            "position_value": round(entry_price * position_size, 2)
        }

    def kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Calcula a fração de Kelly para sizing.

        Args:
            win_rate: Taxa de acerto (0-1)
            avg_win: Ganho médio
            avg_loss: Perda média

        Returns:
            Fração de Kelly (0-1)
        """
        if avg_loss == 0:
            return 0

        win_loss_ratio = avg_win / abs(avg_loss)
        kelly = win_rate - ((1 - win_rate) / win_loss_ratio)

        # Limita a fração de Kelly para ser conservador
        return max(0, min(kelly * 0.5, 0.25))  # Half-Kelly, max 25%
