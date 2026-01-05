"""
Testes para o módulo de risco
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

import sys
# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.risk_math import RiskCalculator, RiskMetrics
from src.execution.position_sizer import PositionSizer, PositionSize


class TestRiskCalculator:
    """Testes para RiskCalculator."""

    @pytest.fixture
    def config(self):
        """Configuração de teste."""
        return {
            "risk": {
                "max_drawdown_daily": 0.02,
                "max_drawdown_total": 0.06,
                "risk_per_trade": 0.01,
                "max_positions": 5
            }
        }

    @pytest.fixture
    def calculator(self, config):
        """Instância do calculator."""
        return RiskCalculator(config)

    @pytest.fixture
    def sample_prices(self):
        """Série de preços de exemplo."""
        dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
        prices = 100 + np.cumsum(np.random.randn(100) * 2)
        return pd.DataFrame({'Close': prices}, index=dates)

    def test_calculate_position_risk(self, calculator):
        """Testa cálculo de risco de posição."""
        result = calculator.calculate_position_risk(
            entry_price=100.0,
            stop_loss=95.0,
            position_size=100
        )

        assert result['risk_per_share'] == 5.0
        assert result['total_risk'] == 500.0
        assert result['risk_percent'] == 5.0
        assert result['position_value'] == 10000.0

    def test_kelly_criterion_basic(self, calculator):
        """Testa Kelly Criterion básico."""
        # 60% win rate, 2:1 reward/risk
        kelly = calculator.kelly_criterion(
            win_rate=0.6,
            avg_win=200.0,
            avg_loss=100.0
        )

        # Kelly = 0.6 - (0.4/2) = 0.6 - 0.2 = 0.4
        # Half-Kelly = 0.2, mas limitado a 0.25
        assert 0 < kelly <= 0.25

    def test_kelly_criterion_zero_loss(self, calculator):
        """Testa Kelly com perda zero."""
        kelly = calculator.kelly_criterion(
            win_rate=0.6,
            avg_win=200.0,
            avg_loss=0.0
        )

        assert kelly == 0

    def test_kelly_criterion_negative(self, calculator):
        """Testa Kelly negativo (estratégia perdedora)."""
        kelly = calculator.kelly_criterion(
            win_rate=0.3,
            avg_win=100.0,
            avg_loss=100.0
        )

        # Kelly negativo deve retornar 0
        assert kelly == 0


class TestPositionSizer:
    """Testes para PositionSizer."""

    @pytest.fixture
    def config(self):
        """Configuração de teste."""
        return {
            "risk": {
                "risk_per_trade": 0.01,
                "max_positions": 5
            },
            "tiers": {
                "tier1_large_cap": {"position_multiplier": 1.0},
                "tier2_mid_cap": {"position_multiplier": 0.7},
                "tier3_small_cap": {"position_multiplier": 0.5}
            }
        }

    @pytest.fixture
    def sizer(self, config):
        """Instância do sizer."""
        return PositionSizer(config)

    def test_calculate_basic(self, sizer):
        """Testa cálculo básico de tamanho."""
        result = sizer.calculate(
            capital=100000,
            entry_price=100.0,
            stop_loss=95.0,
            ticker="AAPL",
            tier="tier1_large_cap",
            size_suggestion="NORMAL"
        )

        # Risco = $1000 (1% de 100k)
        # Risco por ação = $5
        # Shares = 1000 / 5 = 200
        assert result.shares == 200
        assert result.risk_amount == 1000.0
        assert result.ticker == "AAPL"

    def test_calculate_tier2_reduction(self, sizer):
        """Testa redução por tier."""
        result = sizer.calculate(
            capital=100000,
            entry_price=100.0,
            stop_loss=95.0,
            ticker="MID",
            tier="tier2_mid_cap",
            size_suggestion="NORMAL"
        )

        # Risco = $700 (1% * 0.7)
        # Shares = 700 / 5 = 140
        assert result.shares == 140
        assert result.tier_multiplier == 0.7

    def test_calculate_reduced_suggestion(self, sizer):
        """Testa sugestão reduzida."""
        result = sizer.calculate(
            capital=100000,
            entry_price=100.0,
            stop_loss=95.0,
            ticker="AAPL",
            tier="tier1_large_cap",
            size_suggestion="REDUZIDO"
        )

        # Risco = $500 (1% * 0.5)
        # Shares = 500 / 5 = 100
        assert result.shares == 100

    def test_calculate_max_position_limit(self, sizer):
        """Testa limite máximo de posição."""
        result = sizer.calculate(
            capital=100000,
            entry_price=10.0,  # Preço baixo = muitas ações
            stop_loss=9.99,    # Stop muito próximo
            ticker="CHEAP",
            tier="tier1_large_cap",
            size_suggestion="NORMAL"
        )

        # Não deve exceder 20% do capital
        assert result.position_value <= 20000

    def test_validate_size_max_positions(self, sizer):
        """Testa validação de máximo de posições."""
        size = PositionSize(
            ticker="TEST",
            shares=100,
            position_value=10000,
            risk_amount=500,
            risk_percent=1.0,
            tier_multiplier=1.0,
            reason="Test"
        )

        valid, reason = sizer.validate_size(
            size=size,
            current_positions=5,  # Já no máximo
            total_exposure=50000,
            capital=100000
        )

        assert valid is False
        assert "máximo" in reason.lower()

    def test_validate_size_exposure_limit(self, sizer):
        """Testa limite de exposição total."""
        size = PositionSize(
            ticker="TEST",
            shares=100,
            position_value=30000,  # 30% do capital
            risk_amount=500,
            risk_percent=1.0,
            tier_multiplier=1.0,
            reason="Test"
        )

        valid, reason = sizer.validate_size(
            size=size,
            current_positions=2,
            total_exposure=60000,  # 60% já exposto
            capital=100000
        )

        # 60% + 30% = 90% > 80% limite
        assert valid is False
        assert "exposição" in reason.lower()


class TestRiskMetrics:
    """Testes para RiskMetrics."""

    def test_risk_metrics_dataclass(self):
        """Testa criação de RiskMetrics."""
        metrics = RiskMetrics(
            ticker="AAPL",
            beta=1.2,
            volatility_20d=25.5,
            volatility_60d=22.3,
            sharpe_ratio=1.5,
            max_drawdown=15.0,
            var_95=3.2,
            cvar_95=4.5
        )

        assert metrics.ticker == "AAPL"
        assert metrics.beta == 1.2
        assert metrics.volatility_20d == 25.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
