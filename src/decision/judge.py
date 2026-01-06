"""
JUDGE - Juiz Final com IA (FASE 3)
Usa GPT-4/5 + RAG para decisão final
"""

import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .ai_gateway import AIGateway, AIProvider
from src.core.database import Database
from src.decision.grounding import GroundingService

logger = logging.getLogger(__name__)

# Caminho raiz do projeto
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class TradeDecision:
    """Decisão final do Juiz."""
    ticker: str
    decisao: str  # "APROVAR", "REJEITAR", "AGUARDAR"
    nota_final: float
    direcao: str  # "LONG", "SHORT"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risco_recompensa: float
    tamanho_sugerido: str  # "NORMAL", "REDUZIDO", "MÍNIMO"
    justificativa: str
    alertas: List[str]
    validade_horas: int
    timestamp: datetime


class Judge:
    """
    Juiz final do sistema IARA.
    FASE 3 do pipeline - Decisão com GPT + RAG.
    """

    def __init__(self, config: Dict[str, Any], ai_gateway: AIGateway,
                 grounding_service: Optional[GroundingService] = None):
        """
        Inicializa o juiz.

        Args:
            config: Configurações do sistema
            ai_gateway: Gateway de IA
            grounding_service: Serviço de Google Grounding (opcional)
        """
        self.config = config
        self.ai_gateway = ai_gateway
        self.grounding_service = grounding_service
        self.threshold = config.get("ai", {}).get("judge_threshold", 8)
        self._load_prompt_template()
        self._load_rag_context()
        # WS4: Initialize database for caching and logging
        self.db = Database(PROJECT_ROOT / "data" / "iara.db")

    def _load_prompt_template(self) -> None:
        """Carrega template de prompt."""
        try:
            template_path = PROJECT_ROOT / "config" / "prompts" / "judge.md"
            with open(template_path, "r", encoding="utf-8") as f:
                self.prompt_template = f.read()
        except FileNotFoundError:
            logger.warning("Template de juiz não encontrado, usando default")
            self.prompt_template = self._get_default_template()

    def _get_default_template(self) -> str:
        """Template padrão do juiz."""
        return """
Você é o JUIZ FINAL. Analise {ticker} e decida se deve aprovar a operação.

Nota do Screener: {screener_nota}/10
Preço: ${price}
RSI: {rsi}
VIX: {vix}
Correlação: {correlation}

Responda em JSON com: decisao, nota_final, direcao, entry_price, stop_loss, take_profit_1, take_profit_2, justificativa
"""

    def _load_rag_context(self) -> None:
        """Carrega contexto RAG dos manuais."""
        self.rag_context = ""
        rag_path = PROJECT_ROOT / "data" / "rag_manuals"

        if rag_path.exists():
            for file in rag_path.glob("*.md"):
                try:
                    content = file.read_text(encoding="utf-8")
                    self.rag_context += f"\n\n--- {file.name} ---\n{content}"
                except Exception as e:
                    logger.warning(f"Erro ao ler {file}: {e}")

    async def judge(self, ticker: str, screener_result: Dict[str, Any],
                    market_data: Dict[str, Any], technical_data: Dict[str, Any],
                    macro_data: Dict[str, Any], correlation_data: Dict[str, Any],
                    news_details: str = "", correlation_analyzer=None,
                    portfolio_prices: Optional[Dict] = None) -> TradeDecision:
        """
        Executa julgamento final com Google Grounding, Cache e Correlation Validation (WS4).

        Args:
            ticker: Símbolo do ativo
            screener_result: Resultado da triagem
            market_data: Dados de mercado
            technical_data: Dados técnicos
            macro_data: Dados macro
            correlation_data: Dados de correlação
            news_details: Detalhes de notícias
            correlation_analyzer: Instância do CorrelationAnalyzer (para validation)
            portfolio_prices: Dict de preços do portfolio (para correlation check)

        Returns:
            TradeDecision
        """
        try:
            # WS4.1: Check cache ANTES de processar (< 2h com setup idêntico)
            cached = self.db.get_cached_decision(ticker, max_age_hours=2)
            if cached:
                logger.info(f"Cache HIT: {ticker} - reusing decision from {cached.get('timestamp')}")

                # Extrair e validar timestamp antes de usar fromisoformat
                cached_timestamp = cached.get("timestamp")
                if isinstance(cached_timestamp, str):
                    decision_time = datetime.fromisoformat(cached_timestamp)
                else:
                    decision_time = datetime.now()

                # Convert cached dict to TradeDecision
                return TradeDecision(
                    ticker=ticker,
                    decisao=cached.get("decisao", "REJEITAR"),
                    nota_final=cached.get("nota_final", 0),
                    direcao=cached.get("direcao", "NEUTRO"),
                    entry_price=cached.get("entry_price", 0),
                    stop_loss=cached.get("stop_loss", 0),
                    take_profit_1=cached.get("take_profit_1", 0),
                    take_profit_2=cached.get("take_profit_2", 0),
                    risco_recompensa=cached.get("risco_recompensa", 0),
                    tamanho_sugerido=cached.get("tamanho_sugerido", "NORMAL"),
                    justificativa=cached.get("justificativa", ""),
                    alertas=cached.get("alertas", []),
                    validade_horas=cached.get("validade_horas", 4),
                    timestamp=decision_time
                )

            # WS4.2: Google Grounding Pre-Check (se news existe)
            grounded_news = news_details
            if self.grounding_service and news_details:
                logger.info(f"Google Grounding: Verifying news for {ticker}...")
                grounding_result = await self.grounding_service.verify_news(ticker, news_details)

                if grounding_result.verified:
                    # Augmentar news com fontes verificadas
                    sources = grounding_result.sources
                    grounded_news = f"{news_details}\n\nVerified Sources:\n" + "\n".join(f"- {s}" for s in sources[:3])
                    logger.info(f"Google Grounding: {len(sources)} sources verified")
                elif grounding_result.confidence < 0.3:
                    # News não verificado com baixa confiança - rejeitar
                    logger.warning(f"Google Grounding: Low confidence ({grounding_result.confidence:.2f}) - rejecting {ticker}")
                    decision = self._create_rejection(ticker, "News não verificado (baixa confiança)")
                    self.db.log_decision(ticker, decision.__dict__)
                    return decision

            # Monta prompt completo (com news grounded)
            prompt = self._build_prompt(
                ticker, screener_result, market_data, technical_data,
                macro_data, correlation_data, grounded_news
            )

            # Chama IA (prefere OpenAI por qualidade)
            response = await self.ai_gateway.complete(
                prompt=prompt,
                preferred_provider=AIProvider.OPENAI,
                temperature=0.2,
                max_tokens=1500
            )

            if not response.success or not response.parsed_json:
                logger.error(f"Falha no julgamento de {ticker}")
                decision = self._create_rejection(ticker, "Falha na análise de IA")
                self.db.log_decision(ticker, decision.__dict__)
                return decision

            # Valida e processa resposta
            decision = self._parse_decision(ticker, response.parsed_json)

            # WS4.3: Correlation Validation (se APROVAR)
            if decision.decisao == "APROVAR" and correlation_analyzer and portfolio_prices:
                # Fetch preços do ticker
                import yfinance as yf
                ticker_obj = yf.Ticker(ticker)
                hist = ticker_obj.history(period="60d")

                if not hist.empty:
                    ticker_prices = hist["Close"]

                    # Enforce correlation limit
                    is_allowed, violated_tickers = correlation_analyzer.enforce_correlation_limit(
                        ticker, ticker_prices, portfolio_prices
                    )

                    if not is_allowed:
                        # HARD VETO - mudar decisão para REJEITAR
                        logger.error(f"CORRELATION VETO: {ticker} rejected (correlation with {violated_tickers})")
                        decision.decisao = "REJEITAR"
                        decision.nota_final = 0
                        decision.justificativa = f"VETO: Correlação > 0.75 com {', '.join(violated_tickers)}"
                        decision.alertas.append(f"Correlation veto: {', '.join(violated_tickers)}")

            # WS4.4: Cache e log decision
            self.db.cache_decision(ticker, decision.__dict__)
            self.db.log_decision(ticker, decision.__dict__)

            return decision

        except Exception as e:
            logger.error(f"Erro no julgamento de {ticker}: {e}")
            decision = self._create_rejection(ticker, str(e))
            self.db.log_decision(ticker, decision.__dict__)
            return decision

    def _build_prompt(self, ticker: str, screener_result: Dict,
                      market_data: Dict, technical_data: Dict,
                      macro_data: Dict, correlation_data: Dict,
                      news_details: str) -> str:
        """Constrói o prompt completo para o juiz."""
        return self.prompt_template.format(
            ticker=ticker,
            screener_nota=screener_result.get("nota", 0),
            price=market_data.get("price", 0),
            market_cap=market_data.get("market_cap", 0),
            tier=market_data.get("tier", "unknown"),
            beta=market_data.get("beta", 1),
            volatility=technical_data.get("volatility_20d", 0),
            rsi=technical_data.get("rsi", 50),
            atr=technical_data.get("atr", 0),
            supertrend=technical_data.get("supertrend_direction", "neutral"),
            volume_ratio=technical_data.get("volume_ratio", 1),
            support=technical_data.get("support", 0),
            resistance=technical_data.get("resistance", 0),
            vix=macro_data.get("vix", 20),
            spy_trend=macro_data.get("spy_trend", "neutral"),
            sector_perf=market_data.get("sector_perf", 0),
            correlation=correlation_data.get("max_correlation", 0),
            sector_exposure=correlation_data.get("sector_exposure", 0),
            news_details=news_details or "Sem notícias adicionais",
            rag_context=self.rag_context[:3000] if self.rag_context else "Sem manuais carregados"
        )

    def _parse_decision(self, ticker: str, data: Dict) -> TradeDecision:
        """Processa a decisão da IA."""
        decisao = data.get("decisao", "REJEITAR")
        nota = float(data.get("nota_final", 0))

        # Valida regras de negócio
        alerts = data.get("alertas", [])

        # Força rejeição se nota abaixo do threshold
        if nota < self.threshold and decisao == "APROVAR":
            decisao = "REJEITAR"
            alerts.append(f"Nota {nota} abaixo do threshold {self.threshold}")

        return TradeDecision(
            ticker=ticker,
            decisao=decisao,
            nota_final=nota,
            direcao=data.get("direcao", "LONG"),
            entry_price=float(data.get("entry_price", 0)),
            stop_loss=float(data.get("stop_loss", 0)),
            take_profit_1=float(data.get("take_profit_1", 0)),
            take_profit_2=float(data.get("take_profit_2", 0)),
            risco_recompensa=float(data.get("risco_recompensa", 0)),
            tamanho_sugerido=data.get("tamanho_posicao_sugerido", "NORMAL"),
            justificativa=data.get("justificativa", ""),
            alertas=alerts,
            validade_horas=int(data.get("validade_horas", 4)),
            timestamp=datetime.now()
        )

    def _create_rejection(self, ticker: str, reason: str) -> TradeDecision:
        """Cria uma decisão de rejeição."""
        return TradeDecision(
            ticker=ticker,
            decisao="REJEITAR",
            nota_final=0,
            direcao="NEUTRO",
            entry_price=0,
            stop_loss=0,
            take_profit_1=0,
            take_profit_2=0,
            risco_recompensa=0,
            tamanho_sugerido="MÍNIMO",
            justificativa=reason,
            alertas=[reason],
            validade_horas=0,
            timestamp=datetime.now()
        )

    def validate_decision(self, decision: TradeDecision,
                          current_positions: List[Any]) -> bool:
        """
        Valida decisão contra regras de negócio.

        Args:
            decision: Decisão a validar
            current_positions: Posições atuais

        Returns:
            True se válida
        """
        # Verifica se já tem posição no mesmo ativo
        for pos in current_positions:
            if pos.get("ticker") == decision.ticker:
                logger.warning(f"Já existe posição em {decision.ticker}")
                return False

        # Verifica risco/recompensa mínimo
        if decision.risco_recompensa < 2.0:
            logger.warning(f"R/R de {decision.risco_recompensa} abaixo de 2:1")
            return False

        return True
