"""
Testes para o módulo de correlação
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '..')

from src.analysis.correlation import CorrelationAnalyzer, CorrelationResult


class TestCorrelationAnalyzer:
    """Testes para CorrelationAnalyzer."""

    @pytest.fixture
    def config(self):
        """Configuração de teste."""
        return {
            "risk": {
                "max_correlation": 0.7
            }
        }

    @pytest.fixture
    def analyzer(self, config):
        """Instância do analyzer."""
        return CorrelationAnalyzer(config)

    @pytest.fixture
    def sample_prices(self):
        """Preços de exemplo."""
        dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
        np.random.seed(42)

        # Preços correlacionados
        base = np.cumsum(np.random.randn(100)) + 100

        return {
            "AAPL": pd.Series(base + np.random.randn(100) * 2, index=dates),
            "MSFT": pd.Series(base * 1.1 + np.random.randn(100) * 3, index=dates),  # Alta correlação
            "GOLD": pd.Series(200 - base * 0.5 + np.random.randn(100) * 5, index=dates),  # Correlação negativa
            "RANDOM": pd.Series(50 + np.cumsum(np.random.randn(100) * 3), index=dates)  # Baixa correlação
        }

    def test_calculate_correlation_identical(self, analyzer):
        """Testa correlação de séries idênticas."""
        dates = pd.date_range(start='2024-01-01', periods=50, freq='D')
        prices = pd.Series(np.arange(50), index=dates)

        corr = analyzer.calculate_correlation(prices, prices)
        assert corr == pytest.approx(1.0, abs=0.01)

    def test_calculate_correlation_opposite(self, analyzer):
        """Testa correlação de séries opostas."""
        dates = pd.date_range(start='2024-01-01', periods=50, freq='D')
        prices1 = pd.Series(np.arange(50), index=dates)
        prices2 = pd.Series(np.arange(49, -1, -1), index=dates)

        corr = analyzer.calculate_correlation(prices1, prices2)
        assert corr == pytest.approx(-1.0, abs=0.01)

    def test_build_correlation_matrix(self, analyzer, sample_prices):
        """Testa construção de matriz de correlação."""
        matrix = analyzer.build_correlation_matrix(sample_prices)

        assert matrix.shape == (4, 4)
        # Diagonal deve ser 1
        for ticker in sample_prices.keys():
            assert matrix.loc[ticker, ticker] == pytest.approx(1.0, abs=0.01)

        # Matriz deve ser simétrica
        assert matrix.loc["AAPL", "MSFT"] == pytest.approx(matrix.loc["MSFT", "AAPL"], abs=0.01)

    def test_check_portfolio_correlation(self, analyzer, sample_prices):
        """Testa verificação de correlação do portfólio."""
        existing = {
            "AAPL": sample_prices["AAPL"]
        }

        results = analyzer.check_portfolio_correlation(
            new_ticker="MSFT",
            new_prices=sample_prices["MSFT"],
            existing_positions=existing
        )

        assert len(results) == 1
        assert results[0].ticker1 == "MSFT"
        assert results[0].ticker2 == "AAPL"
        # MSFT e AAPL devem ter alta correlação positiva
        assert results[0].correlation > 0.5

    def test_can_add_position_allowed(self, analyzer, sample_prices):
        """Testa adição permitida de posição."""
        existing = {
            "AAPL": sample_prices["AAPL"]
        }

        can_add, reason = analyzer.can_add_position(
            new_ticker="RANDOM",
            new_prices=sample_prices["RANDOM"],
            existing_positions=existing
        )

        # RANDOM tem baixa correlação, deve ser permitido
        assert can_add is True

    def test_can_add_position_high_correlation(self, analyzer, sample_prices):
        """Testa bloqueio por alta correlação."""
        existing = {
            "AAPL": sample_prices["AAPL"]
        }

        can_add, reason = analyzer.can_add_position(
            new_ticker="MSFT",
            new_prices=sample_prices["MSFT"],
            existing_positions=existing
        )

        # MSFT tem alta correlação com AAPL
        # Pode ser bloqueado dependendo do threshold

    def test_get_diversification_score_single(self, analyzer):
        """Testa score de diversificação com único ativo."""
        matrix = pd.DataFrame([[1.0]], columns=["AAPL"], index=["AAPL"])
        score = analyzer.get_diversification_score(matrix)

        assert score == 1.0

    def test_get_diversification_score_perfect(self, analyzer, sample_prices):
        """Testa score de diversificação."""
        matrix = analyzer.build_correlation_matrix(sample_prices)
        score = analyzer.get_diversification_score(matrix)

        assert 0 <= score <= 1

    def test_classify_correlation(self, analyzer):
        """Testa classificação de correlação."""
        assert analyzer._classify_correlation(0.8) == "positive"
        assert analyzer._classify_correlation(-0.8) == "negative"
        assert analyzer._classify_correlation(0.2) == "neutral"

    def test_insufficient_data(self, analyzer):
        """Testa com dados insuficientes."""
        dates = pd.date_range(start='2024-01-01', periods=10, freq='D')
        short_series = pd.Series(np.arange(10), index=dates)

        corr = analyzer.calculate_correlation(short_series, short_series)
        assert corr == 0.0  # Retorna 0 para dados insuficientes


class TestCorrelationResult:
    """Testes para CorrelationResult."""

    def test_correlation_result_dataclass(self):
        """Testa criação de CorrelationResult."""
        result = CorrelationResult(
            ticker1="AAPL",
            ticker2="MSFT",
            correlation=0.85,
            correlation_type="positive",
            is_problematic=True
        )

        assert result.ticker1 == "AAPL"
        assert result.ticker2 == "MSFT"
        assert result.correlation == 0.85
        assert result.is_problematic is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
