"""
CORRELATION ANALYZER - Matriz de Correlação (FASE 2)
Análise de correlação cruzada entre ativos
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CorrelationResult:
    """Resultado de análise de correlação."""
    ticker1: str
    ticker2: str
    correlation: float
    correlation_type: str  # "positive", "negative", "neutral"
    is_problematic: bool  # True se correlação > threshold


class CorrelationAnalyzer:
    """
    Analisador de correlação para gestão de risco do portfólio.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o analisador.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.max_correlation = config.get("risk", {}).get("max_correlation", 0.7)
        self._price_cache: Dict[str, pd.Series] = {}

    def calculate_correlation(self, prices1: pd.Series, prices2: pd.Series) -> float:
        """
        Calcula correlação entre duas séries de preços.

        Args:
            prices1: Série de preços do ativo 1
            prices2: Série de preços do ativo 2

        Returns:
            Coeficiente de correlação
        """
        returns1 = prices1.pct_change().dropna()
        returns2 = prices2.pct_change().dropna()

        # Alinha as séries
        aligned = pd.concat([returns1, returns2], axis=1).dropna()

        if len(aligned) < 20:
            logger.warning("Dados insuficientes para cálculo de correlação")
            return 0.0

        return aligned.iloc[:, 0].corr(aligned.iloc[:, 1])

    def build_correlation_matrix(self, price_data: Dict[str, pd.Series]) -> pd.DataFrame:
        """
        Constrói matriz de correlação para múltiplos ativos.

        Args:
            price_data: Dict ticker -> série de preços

        Returns:
            DataFrame com matriz de correlação
        """
        tickers = list(price_data.keys())

        if len(tickers) < 2:
            return pd.DataFrame()

        # Converte preços em retornos
        returns_data = {}
        for ticker, prices in price_data.items():
            returns_data[ticker] = prices.pct_change().dropna()

        # Cria DataFrame de retornos
        returns_df = pd.DataFrame(returns_data).dropna()

        return returns_df.corr()

    def check_portfolio_correlation(self, new_ticker: str, new_prices: pd.Series,
                                    existing_positions: Dict[str, pd.Series]) -> List[CorrelationResult]:
        """
        Verifica correlação de um novo ativo com posições existentes.

        Args:
            new_ticker: Ticker do novo ativo
            new_prices: Série de preços do novo ativo
            existing_positions: Dict ticker -> preços das posições abertas

        Returns:
            Lista de resultados de correlação
        """
        results = []

        for ticker, prices in existing_positions.items():
            corr = self.calculate_correlation(new_prices, prices)

            result = CorrelationResult(
                ticker1=new_ticker,
                ticker2=ticker,
                correlation=corr,
                correlation_type=self._classify_correlation(corr),
                is_problematic=abs(corr) > self.max_correlation
            )
            results.append(result)

            if result.is_problematic:
                logger.warning(f"Alta correlação detectada: {new_ticker} x {ticker} = {corr:.2f}")

        return results

    def _classify_correlation(self, corr: float) -> str:
        """Classifica o tipo de correlação."""
        if corr > 0.5:
            return "positive"
        elif corr < -0.5:
            return "negative"
        else:
            return "neutral"

    def can_add_position(self, new_ticker: str, new_prices: pd.Series,
                         existing_positions: Dict[str, pd.Series]) -> Tuple[bool, str]:
        """
        Verifica se pode adicionar nova posição sem violar limites de correlação.

        Args:
            new_ticker: Ticker do novo ativo
            new_prices: Preços do novo ativo
            existing_positions: Posições existentes

        Returns:
            Tuple (pode_adicionar, motivo)
        """
        if not existing_positions:
            return True, "Nenhuma posição existente"

        correlations = self.check_portfolio_correlation(new_ticker, new_prices, existing_positions)

        problematic = [r for r in correlations if r.is_problematic]

        if problematic:
            tickers = [r.ticker2 for r in problematic]
            return False, f"Alta correlação com: {', '.join(tickers)}"

        return True, "Correlação dentro dos limites"

    def enforce_correlation_limit(self, new_ticker: str, new_prices: pd.Series,
                                  existing_positions: Dict[str, pd.Series]) -> Tuple[bool, List[str]]:
        """
        HARD VETO - Enforce correlation limit (WS3).
        Este método é NON-NEGOTIABLE e rejeita qualquer ativo com correlação > max_correlation.

        Args:
            new_ticker: Ticker do novo ativo
            new_prices: Série de preços do novo ativo
            existing_positions: Dict ticker -> preços das posições abertas

        Returns:
            Tuple (is_allowed, violated_tickers)
            - is_allowed: False se VETO (correlação > threshold com QUALQUER posição)
            - violated_tickers: Lista de tickers com correlação problemática
        """
        if not existing_positions:
            logger.debug(f"Correlation check for {new_ticker}: PASSED (no existing positions)")
            return True, []

        # Verifica correlação com TODAS as posições
        correlations = self.check_portfolio_correlation(new_ticker, new_prices, existing_positions)

        # Identifica violações
        violated_tickers = []
        for result in correlations:
            if result.is_problematic:
                violated_tickers.append(result.ticker2)
                logger.warning(f"CORRELATION VETO: {new_ticker} x {result.ticker2} = {result.correlation:.3f} "
                               f"(max {self.max_correlation:.2f})")

        if violated_tickers:
            logger.error(f"HARD VETO: {new_ticker} rejected due to correlation > {self.max_correlation:.2f} "
                         f"with {len(violated_tickers)} position(s): {', '.join(violated_tickers)}")
            return False, violated_tickers

        logger.info(f"Correlation check for {new_ticker}: PASSED (all correlations < {self.max_correlation:.2f})")
        return True, []

    def get_diversification_score(self, correlation_matrix: pd.DataFrame) -> float:
        """
        Calcula score de diversificação do portfólio.

        Args:
            correlation_matrix: Matriz de correlação

        Returns:
            Score de 0 (não diversificado) a 1 (bem diversificado)
        """
        if correlation_matrix.empty:
            return 1.0

        # Média das correlações (excluindo diagonal)
        n = len(correlation_matrix)
        if n <= 1:
            return 1.0

        # Soma das correlações fora da diagonal
        total_corr: float = 0.0
        count = 0
        # Usar .values para obter array numpy com tipos numéricos claros
        corr_values = correlation_matrix.values
        for i in range(n):
            for j in range(i + 1, n):
                # corr_values[i, j] é numpy.float64, conversão segura
                total_corr += abs(float(corr_values[i, j]))
                count += 1

        avg_corr = total_corr / count if count > 0 else 0

        # Score inverso: quanto menor a correlação média, melhor
        return max(0, 1 - avg_corr)

    def get_sector_correlation(self, tickers: List[str], sector_map: Dict[str, str],
                               price_data: Dict[str, pd.Series]) -> Dict[str, float]:
        """
        Calcula correlação média por setor.

        Args:
            tickers: Lista de tickers
            sector_map: Mapeamento ticker -> setor
            price_data: Dados de preço

        Returns:
            Dict setor -> correlação média intra-setor
        """
        sector_correlations = {}

        # Agrupa tickers por setor
        sectors = {}
        for ticker in tickers:
            sector = sector_map.get(ticker, "Unknown")
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(ticker)

        # Calcula correlação média intra-setor
        for sector, sector_tickers in sectors.items():
            if len(sector_tickers) < 2:
                sector_correlations[sector] = 0.0
                continue

            correlations = []
            for i, t1 in enumerate(sector_tickers):
                for t2 in sector_tickers[i + 1:]:
                    if t1 in price_data and t2 in price_data:
                        corr = self.calculate_correlation(price_data[t1], price_data[t2])
                        correlations.append(abs(corr))

            sector_correlations[sector] = np.mean(correlations) if correlations else 0.0

        return sector_correlations
