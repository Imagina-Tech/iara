"""
SCREENER - Triagem com IA (FASE 1)
Usa Gemini Free para avaliação inicial
"""

import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .ai_gateway import AIGateway, AIProvider

logger = logging.getLogger(__name__)

# Caminho raiz do projeto
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class ScreenerResult:
    """Resultado da triagem."""
    ticker: str
    nota: float
    resumo: str
    vies: str  # "LONG", "SHORT", "NEUTRO"
    confianca: float
    passed: bool
    timestamp: datetime


class Screener:
    """
    Screener de ativos usando Gemini Free.
    FASE 1 do pipeline de decisão.
    """

    def __init__(self, config: Dict[str, Any], ai_gateway: AIGateway):
        """
        Inicializa o screener.

        Args:
            config: Configurações do sistema
            ai_gateway: Gateway de IA
        """
        self.config = config
        self.ai_gateway = ai_gateway
        self.threshold = config.get("ai", {}).get("screener_threshold", 7)
        self._load_prompt_template()

    def _load_prompt_template(self) -> None:
        """Carrega template de prompt do arquivo."""
        try:
            template_path = PROJECT_ROOT / "config" / "prompts" / "screener.md"
            with open(template_path, "r", encoding="utf-8") as f:
                self.prompt_template = f.read()
        except FileNotFoundError:
            logger.warning("Template de screener não encontrado, usando default")
            self.prompt_template = self._get_default_template()

    def _get_default_template(self) -> str:
        """Template padrão de screener."""
        return """
Analise o ativo {ticker} e dê uma nota de 0 a 10.

Dados:
- Preço: ${price}
- Variação: {change_pct}%
- Volume Ratio: {volume_ratio}x
- RSI: {rsi}
- SuperTrend: {supertrend_signal}

Responda em JSON:
{{"ticker": "{ticker}", "nota": 0, "resumo": "", "viés": "NEUTRO", "confianca": 0.0}}
"""

    async def screen(self, market_data: Dict[str, Any],
                     technical_data: Dict[str, Any],
                     news_summary: str = "") -> ScreenerResult:
        """
        Executa triagem de um ativo.

        Args:
            market_data: Dados de mercado
            technical_data: Dados técnicos
            news_summary: Resumo de notícias

        Returns:
            ScreenerResult
        """
        ticker = market_data.get("ticker", "UNKNOWN")

        try:
            # Monta o prompt
            prompt = self.prompt_template.format(
                ticker=ticker,
                price=market_data.get("price", 0),
                change_pct=market_data.get("change_pct", 0),
                volume_ratio=technical_data.get("volume_ratio", 1),
                rsi=technical_data.get("rsi", 50),
                atr=technical_data.get("atr", 0),
                supertrend_signal=technical_data.get("supertrend_direction", "neutral"),
                news_summary=news_summary or "Sem notícias recentes"
            )

            # Chama IA (prefere Gemini por ser gratuito)
            response = await self.ai_gateway.complete(
                prompt=prompt,
                preferred_provider=AIProvider.GEMINI,
                temperature=0.3,
                max_tokens=500
            )

            if not response.success or not response.parsed_json:
                logger.error(f"Falha na triagem de {ticker}")
                return self._create_failed_result(ticker)

            # Processa resposta
            result_data = response.parsed_json
            nota = float(result_data.get("nota", 0))

            return ScreenerResult(
                ticker=ticker,
                nota=nota,
                resumo=result_data.get("resumo", ""),
                vies=result_data.get("viés", "NEUTRO"),
                confianca=float(result_data.get("confianca", 0)),
                passed=nota >= self.threshold,
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"Erro na triagem de {ticker}: {e}")
            return self._create_failed_result(ticker)

    async def screen_batch(self, candidates: List[Dict]) -> List[ScreenerResult]:
        """
        Executa triagem em lote.

        Args:
            candidates: Lista de candidatos com market_data e technical_data

        Returns:
            Lista de ScreenerResult
        """
        results = []

        for candidate in candidates:
            result = await self.screen(
                market_data=candidate.get("market_data", {}),
                technical_data=candidate.get("technical_data", {}),
                news_summary=candidate.get("news_summary", "")
            )
            results.append(result)

        # Ordena por nota decrescente
        results.sort(key=lambda x: x.nota, reverse=True)

        passed_count = sum(1 for r in results if r.passed)
        logger.info(f"Triagem concluída: {passed_count}/{len(results)} passaram")

        return results

    def _create_failed_result(self, ticker: str) -> ScreenerResult:
        """Cria resultado de falha."""
        return ScreenerResult(
            ticker=ticker,
            nota=0,
            resumo="Falha na análise",
            vies="NEUTRO",
            confianca=0,
            passed=False,
            timestamp=datetime.now()
        )

    def get_passed_candidates(self, results: List[ScreenerResult]) -> List[ScreenerResult]:
        """Filtra candidatos que passaram na triagem."""
        return [r for r in results if r.passed]
