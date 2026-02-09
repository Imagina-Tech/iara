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

# ─── Audit Callback ──────────────────────────────────────────────
_judge_audit_callback = None


def set_judge_audit_callback(cb):
    """Set a callback to receive audit entries from the Judge.

    The callback receives a dict with keys: timestamp, ticker, origin,
    prompt (or summary), result, score, direction, justificativa.
    Thread-safe: the callback should be non-blocking (e.g. queue.put_nowait).
    """
    global _judge_audit_callback
    _judge_audit_callback = cb


def _emit_audit(entry: dict) -> None:
    """Fire the audit callback if set. Never lets exceptions escape."""
    cb = _judge_audit_callback
    if cb is None:
        return
    try:
        cb(entry)
    except Exception:
        pass  # Audit must never break the pipeline


# Caminho raiz do projeto (works both as script and .exe)
import sys
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path.cwd()
else:
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
                    portfolio_prices: Optional[Dict] = None,
                    alpaca_data: str = "",
                    data_coherence: str = "") -> TradeDecision:
        """
        Executa julgamento final com Google Grounding, Cache e Correlation Validation (WS4).

        Supports DUAL BRAIN input:
        - Brain 1 (existing): yfinance market data + GNews + Gemini Screener
        - Brain 2 (new/optional): Alpaca Markets real-time data + Benzinga News

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
            alpaca_data: Dados real-time formatados do Alpaca/Brain 2 (opcional)
            data_coherence: Comparação de coerência entre Brain 1 e Brain 2 (opcional)

        Returns:
            TradeDecision
        """
        logger.info(f"[JUDGE] {ticker}: Starting final judgment (threshold={self.threshold})")
        try:
            # CORRELATION CHECK FIRST (must run BEFORE cache - portfolio may have changed)
            if correlation_analyzer and portfolio_prices:
                logger.info(f"[JUDGE] {ticker}: Checking correlation vs {len(portfolio_prices)} open positions...")
                import asyncio

                # Try to get ticker prices from portfolio_prices first (replay provides them)
                # Only fetch from yfinance if not already available (live mode)
                ticker_prices = portfolio_prices.get(ticker)
                if ticker_prices is None:
                    import yfinance as yf
                    loop = asyncio.get_running_loop()
                    ticker_obj = await loop.run_in_executor(None, lambda t=ticker: yf.Ticker(t))
                    hist = await loop.run_in_executor(None, lambda: ticker_obj.history(period="60d"))
                    if not hist.empty:
                        ticker_prices = hist["Close"]

                if ticker_prices is not None and len(ticker_prices) > 0:
                    # Remove the ticker itself from portfolio_prices to avoid self-correlation
                    check_prices = {k: v for k, v in portfolio_prices.items() if k != ticker}
                    if check_prices:
                        is_allowed, violated_tickers = correlation_analyzer.enforce_correlation_limit(
                            ticker, ticker_prices, check_prices
                        )
                        if not is_allowed:
                            logger.error(f"[JUDGE] CORRELATION VETO: {ticker} rejected (corr with {violated_tickers})")
                            decision = self._create_rejection(
                                ticker, f"VETO: Correlacao > 0.75 com {', '.join(violated_tickers)}"
                            )
                            _emit_audit({
                                "timestamp": datetime.now().isoformat(),
                                "ticker": ticker,
                                "origin": "Phase 3 - Correlation Veto",
                                "prompt": f"Correlation check vs {len(check_prices)} positions. Violated: {violated_tickers}",
                                "result": "REJEITAR",
                                "score": 0,
                                "direction": "NEUTRO",
                                "justificativa": decision.justificativa,
                            })
                            self.db.log_decision(ticker, decision.__dict__)
                            return decision

            # WS4.1: Check cache AFTER correlation (< 2h com setup idêntico)
            # Include portfolio hash in cache key so changes invalidate cache
            portfolio_key = ",".join(sorted(portfolio_prices.keys())) if portfolio_prices else ""
            cached = self.db.get_cached_decision(ticker, max_age_hours=2, portfolio_key=portfolio_key)
            if cached:
                logger.info(f"[JUDGE] {ticker}: CACHE HIT - reusing decision from {cached.get('timestamp')}")

                cached_timestamp = cached.get("timestamp")
                if isinstance(cached_timestamp, str):
                    decision_time = datetime.fromisoformat(cached_timestamp)
                else:
                    decision_time = datetime.now()

                cached_decision = TradeDecision(
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
                _emit_audit({
                    "timestamp": datetime.now().isoformat(),
                    "ticker": ticker,
                    "origin": "Phase 3 - Cache Hit",
                    "prompt": f"[CACHE HIT] Reusing decision from {cached.get('timestamp')}",
                    "result": cached_decision.decisao,
                    "score": cached_decision.nota_final,
                    "direction": cached_decision.direcao,
                    "justificativa": cached_decision.justificativa,
                })
                return cached_decision

            # WS4.2: Google Grounding Pre-Check (se news existe)
            grounded_news = news_details
            if self.grounding_service and news_details:
                logger.info(f"[JUDGE] {ticker}: Google Grounding verifying news...")
                grounding_result = await self.grounding_service.verify_news(ticker, news_details)

                if grounding_result.verified:
                    # Augmentar news com fontes verificadas
                    sources = grounding_result.sources
                    grounded_news = f"{news_details}\n\nVerified Sources:\n" + "\n".join(f"- {s}" for s in sources[:3])
                    logger.info(f"[JUDGE] {ticker}: Grounding OK - {len(sources)} sources (conf={grounding_result.confidence:.2f})")
                elif grounding_result.confidence < 0.3:
                    # News não verificado com baixa confiança - rejeitar
                    logger.warning(f"[JUDGE] {ticker}: Grounding FAILED (conf={grounding_result.confidence:.2f}) - REJECTING")
                    decision = self._create_rejection(ticker, "News não verificado (baixa confiança)")
                    _emit_audit({
                        "timestamp": datetime.now().isoformat(),
                        "ticker": ticker,
                        "origin": "Phase 3 - Grounding Veto",
                        "prompt": f"Google Grounding check failed. Confidence={grounding_result.confidence:.2f}",
                        "result": "REJEITAR",
                        "score": 0,
                        "direction": "NEUTRO",
                        "justificativa": decision.justificativa,
                    })
                    self.db.log_decision(ticker, decision.__dict__)
                    return decision

            # Monta prompt completo (com news grounded + Brain 2 data)
            brain_mode = "DUAL" if alpaca_data else "SINGLE"
            logger.info(f"[JUDGE] {ticker}: Building dossier ({brain_mode} brain) | "
                        f"Screener={screener_result.get('nota', 0)}/10 | "
                        f"RSI={technical_data.get('rsi', '?')} | VIX={macro_data.get('vix', '?')}")
            prompt = self._build_prompt(
                ticker, screener_result, market_data, technical_data,
                macro_data, correlation_data, grounded_news,
                alpaca_data=alpaca_data,
                data_coherence=data_coherence
            )

            # Chama IA (Gemini 3 Pro Preview - 1M input tokens, economico)
            logger.info(f"[JUDGE] {ticker}: Calling AI (preferred=Gemini3Pro, temp=0.2)...")
            response = await self.ai_gateway.complete(
                prompt=prompt,
                preferred_provider=AIProvider.GEMINI_PRO,
                temperature=0.2,
                max_tokens=2500
            )

            if not response.success or not response.parsed_json:
                logger.error(f"[JUDGE] {ticker}: AI FAILED - success={response.success}, "
                             f"json={'present' if response.parsed_json else 'None'}, "
                             f"raw='{response.content[:150]}'")
                decision = self._create_rejection(ticker, "Falha na analise de IA (JSON nao parseado)")
                _emit_audit({
                    "timestamp": datetime.now().isoformat(),
                    "ticker": ticker,
                    "origin": "Phase 3 - AI Failure",
                    "prompt": prompt,
                    "result": "REJEITAR",
                    "score": 0,
                    "direction": "NEUTRO",
                    "justificativa": decision.justificativa,
                })
                self.db.log_decision(ticker, decision.__dict__)
                return decision

            logger.debug(f"[JUDGE] {ticker}: AI response via {response.provider.value}/{response.model} "
                         f"({response.tokens_used} tokens)")

            # Valida e processa resposta
            decision = self._parse_decision(ticker, response.parsed_json)

            # Correlation was already checked BEFORE cache (top of method)

            # Emit audit entry with full prompt and parsed decision
            _emit_audit({
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "origin": "Phase 3 - Judge Decision",
                "prompt": prompt,
                "result": decision.decisao,
                "score": decision.nota_final,
                "direction": decision.direcao,
                "justificativa": decision.justificativa,
            })

            # Log final verdict
            logger.info(f"[JUDGE] {ticker}: VERDICT={decision.decisao} | Score={decision.nota_final}/10 | "
                        f"Dir={decision.direcao} | R/R={decision.risco_recompensa:.1f} | "
                        f"Entry=${decision.entry_price:.2f} SL=${decision.stop_loss:.2f} "
                        f"TP1=${decision.take_profit_1:.2f}")
            if decision.alertas:
                logger.debug(f"[JUDGE] {ticker}: Alerts: {decision.alertas}")

            # WS4.4: Cache e log decision (include portfolio_key for invalidation)
            self.db.cache_decision(ticker, decision.__dict__, portfolio_key=portfolio_key)
            self.db.log_decision(ticker, decision.__dict__)

            return decision

        except Exception as e:
            logger.error(f"[JUDGE] {ticker}: EXCEPTION - {e}")
            decision = self._create_rejection(ticker, str(e))
            _emit_audit({
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "origin": "Phase 3 - Exception",
                "prompt": f"Exception: {e}",
                "result": "REJEITAR",
                "score": 0,
                "direction": "NEUTRO",
                "justificativa": str(e),
            })
            self.db.log_decision(ticker, decision.__dict__)
            return decision

    def _build_prompt(self, ticker: str, screener_result: Dict,
                      market_data: Dict, technical_data: Dict,
                      macro_data: Dict, correlation_data: Dict,
                      news_details: str,
                      alpaca_data: str = "",
                      data_coherence: str = "") -> str:
        """
        Constrói o prompt completo para o juiz.

        Supports DUAL BRAIN: Brain 1 (yfinance/GNews) and Brain 2 (Alpaca/Benzinga).
        If alpaca_data/data_coherence are empty, those sections show fallback text
        and the Judge operates in single-brain mode (backward compatible).
        """
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
            vix_regime=macro_data.get("vix_regime", "normal"),
            spy_price=macro_data.get("spy_price", 0),
            spy_trend=macro_data.get("spy_trend", "neutral"),
            spy_change_pct=macro_data.get("spy_change_pct", 0),
            qqq_price=macro_data.get("qqq_price", 0),
            dxy_price=macro_data.get("dxy_price", 0),
            us10y_yield=macro_data.get("us10y_yield", 0),
            sector_perf=market_data.get("sector_perf", 0),
            correlation=correlation_data.get("max_correlation", 0),
            sector_exposure=correlation_data.get("sector_exposure", 0),
            news_details=news_details or "Sem notícias adicionais",
            alpaca_data=alpaca_data or "Brain 2 indisponivel (modo single-brain)",
            data_coherence=data_coherence or "Apenas Brain 1 ativo - sem comparacao de coerencia",
            rag_context=self.rag_context if self.rag_context else "Sem manuais carregados"
        )

    def _parse_decision(self, ticker: str, data: Dict) -> TradeDecision:
        """Processa a decisao da IA com validacoes de negocio."""
        decisao = data.get("decisao", "REJEITAR")
        nota = float(data.get("nota_final", 0))
        rr = float(data.get("risco_recompensa", 0))
        logger.debug(f"[JUDGE] {ticker}: AI raw verdict={decisao} score={nota} R/R={rr:.1f}")

        # Validate business rules
        alerts = data.get("alertas", [])
        if not isinstance(alerts, list):
            alerts = []

        # Force rejection if score below threshold
        if nota < self.threshold and decisao == "APROVAR":
            decisao = "REJEITAR"
            alerts.append(f"Nota {nota} abaixo do threshold {self.threshold}")
            logger.warning(f"[JUDGE] {ticker}: OVERRIDDEN - score {nota} < threshold {self.threshold}")

        # Force rejection if R/R below 2.0 minimum
        if rr < 2.0 and decisao == "APROVAR":
            decisao = "REJEITAR"
            alerts.append(f"R/R {rr:.1f} abaixo do minimo 2.0")
            logger.warning(f"[JUDGE] {ticker}: OVERRIDDEN - R/R {rr:.1f} < 2.0 minimum")

        # Validate entry/stop/TP prices are reasonable
        entry = float(data.get("entry_price", 0))
        stop = float(data.get("stop_loss", 0))
        tp1 = float(data.get("take_profit_1", 0))

        if decisao == "APROVAR" and entry > 0:
            # Verify stop is on correct side
            direcao = data.get("direcao", "LONG")
            if direcao == "LONG" and stop >= entry:
                alerts.append(f"Stop ${stop:.2f} >= Entry ${entry:.2f} para LONG")
                decisao = "REJEITAR"
                logger.warning(f"[JUDGE] {ticker}: OVERRIDDEN - stop ${stop:.2f} wrong side for LONG")
            elif direcao == "SHORT" and stop <= entry:
                alerts.append(f"Stop ${stop:.2f} <= Entry ${entry:.2f} para SHORT")
                decisao = "REJEITAR"
                logger.warning(f"[JUDGE] {ticker}: OVERRIDDEN - stop ${stop:.2f} wrong side for SHORT")

        return TradeDecision(
            ticker=ticker,
            decisao=decisao,
            nota_final=nota,
            direcao=data.get("direcao", "LONG"),
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=float(data.get("take_profit_2", 0)),
            risco_recompensa=rr,
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
                logger.warning(f"[JUDGE] Validation FAILED: duplicate position in {decision.ticker}")
                return False

        # Verifica risco/recompensa mínimo
        if decision.risco_recompensa < 2.0:
            logger.warning(f"[JUDGE] Validation FAILED: R/R {decision.risco_recompensa:.1f} < 2:1 for {decision.ticker}")
            return False

        logger.info(f"[JUDGE] {decision.ticker}: Post-validation PASSED (R/R={decision.risco_recompensa:.1f})")
        return True
