"""
POSITION SIZER - Cálculo de Lote (FASE 4)
Risco Fixo + Tier Reducer
"""

import logging
from typing import Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Resultado do cálculo de tamanho."""
    ticker: str
    shares: int
    position_value: float
    risk_amount: float
    risk_percent: float
    tier_multiplier: float
    reason: str


class PositionSizer:
    """
    Calculadora de tamanho de posição.
    Usa modelo de risco fixo com ajuste por tier.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa o sizer.

        Args:
            config: Configurações do sistema
        """
        self.config = config
        self.risk_config = config.get("risk", {})
        self.tiers_config = config.get("tiers", {})

    def calculate(self, capital: float, entry_price: float, stop_loss: float,
                  ticker: str, tier: str, size_suggestion: str = "NORMAL") -> PositionSize:
        """
        Calcula tamanho da posição.

        Args:
            capital: Capital disponível
            entry_price: Preço de entrada
            stop_loss: Preço do stop loss
            ticker: Símbolo do ativo
            tier: Tier do ativo (tier1_large_cap, tier2_mid_cap, tier3_small_cap)
            size_suggestion: Sugestão do juiz (NORMAL, REDUZIDO, MÍNIMO)

        Returns:
            PositionSize
        """
        # Risk per trade base
        base_risk_pct = self.risk_config.get("risk_per_trade", 0.01)

        # Ajusta por tier
        tier_config = self.tiers_config.get(tier, {})
        tier_multiplier = tier_config.get("position_multiplier", 1.0)

        # Ajusta por sugestão do juiz
        suggestion_multipliers = {
            "NORMAL": 1.0,
            "REDUZIDO": 0.5,
            "MÍNIMO": 0.25
        }
        suggestion_mult = suggestion_multipliers.get(size_suggestion, 1.0)

        # Risco final
        final_risk_pct = base_risk_pct * tier_multiplier * suggestion_mult
        risk_amount = capital * final_risk_pct

        # Calcula risco por ação
        risk_per_share = abs(entry_price - stop_loss)

        if risk_per_share <= 0:
            logger.error(f"Risco por ação inválido para {ticker}")
            return PositionSize(
                ticker=ticker,
                shares=0,
                position_value=0,
                risk_amount=0,
                risk_percent=0,
                tier_multiplier=tier_multiplier,
                reason="Stop loss inválido"
            )

        # Número de ações
        shares = int(risk_amount / risk_per_share)

        # Verifica limites
        max_position_pct = 0.20  # Máximo 20% do capital em uma posição
        max_position_value = capital * max_position_pct
        position_value = shares * entry_price

        if position_value > max_position_value:
            shares = int(max_position_value / entry_price)
            position_value = shares * entry_price
            reason = f"Limitado a {max_position_pct*100}% do capital"
        else:
            reason = f"Risco {final_risk_pct*100:.1f}% | Tier: {tier_multiplier}x | Sugestão: {size_suggestion}"

        return PositionSize(
            ticker=ticker,
            shares=shares,
            position_value=round(position_value, 2),
            risk_amount=round(shares * risk_per_share, 2),
            risk_percent=round(final_risk_pct * 100, 2),
            tier_multiplier=tier_multiplier,
            reason=reason
        )

    def validate_size(self, size: PositionSize, current_positions: int,
                      total_exposure: float, capital: float) -> tuple[bool, str]:
        """
        Valida se o tamanho está dentro dos limites.

        Args:
            size: Tamanho calculado
            current_positions: Número de posições abertas
            total_exposure: Exposição total atual
            capital: Capital total

        Returns:
            Tuple (válido, motivo)
        """
        max_positions = self.risk_config.get("max_positions", 5)

        # Verifica número de posições
        if current_positions >= max_positions:
            return False, f"Máximo de {max_positions} posições atingido"

        # Verifica exposição total
        max_exposure = 0.80  # Máximo 80% do capital exposto
        new_exposure = total_exposure + size.position_value

        if new_exposure > capital * max_exposure:
            return False, f"Exposição total excederia {max_exposure*100}%"

        # Verifica quantidade mínima
        if size.shares < 1:
            return False, "Quantidade de ações insuficiente"

        return True, "OK"

    def adjust_for_volatility(self, base_size: PositionSize,
                              volatility: float, vix: float) -> PositionSize:
        """
        Ajusta tamanho baseado em volatilidade.

        Args:
            base_size: Tamanho base calculado
            volatility: Volatilidade do ativo (%)
            vix: VIX atual

        Returns:
            PositionSize ajustado
        """
        # Fator de ajuste por volatilidade do ativo
        vol_factor = 1.0
        if volatility > 50:
            vol_factor = 0.5
        elif volatility > 30:
            vol_factor = 0.75

        # Fator de ajuste por VIX
        vix_factor = 1.0
        if vix > 25:
            vix_factor = 0.75
        if vix > 30:
            vix_factor = 0.5

        # Aplica ajustes
        final_factor = vol_factor * vix_factor
        adjusted_shares = int(base_size.shares * final_factor)

        return PositionSize(
            ticker=base_size.ticker,
            shares=adjusted_shares,
            position_value=round(adjusted_shares * (base_size.position_value / base_size.shares), 2) if base_size.shares > 0 else 0,
            risk_amount=round(base_size.risk_amount * final_factor, 2),
            risk_percent=base_size.risk_percent * final_factor,
            tier_multiplier=base_size.tier_multiplier,
            reason=f"{base_size.reason} | Vol adj: {final_factor:.2f}"
        )
