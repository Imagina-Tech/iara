"""
ORCHESTRATOR - Maestro do Sistema IARA
Controla as Fases 0 a 5 e gerencia horários de operação
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Orquestrador principal do sistema IARA.
    Coordena todas as fases do pipeline de trading.
    """

    def __init__(self, config: Dict[str, Any], buzz_factory, screener, risk_calculator,
                 correlation_analyzer, judge, order_manager, position_sizer,
                 state_manager, earnings_checker, market_data):
        """
        Inicializa o orquestrador com TODAS as dependências (WS7).

        Args:
            config: Configurações do sistema (settings.yaml)
            buzz_factory: Phase 0 - Buzz Factory
            screener: Phase 1 - Screener
            risk_calculator: Phase 2 - Risk Math
            correlation_analyzer: Phase 2 - Correlation
            judge: Phase 3 - Judge
            order_manager: Phase 4 - Order Manager
            position_sizer: Phase 4 - Position Sizer
            state_manager: State Manager
            earnings_checker: Earnings Checker
            market_data: Market Data Collector
        """
        self.config = config
        self.buzz_factory = buzz_factory
        self.screener = screener
        self.risk_calculator = risk_calculator
        self.correlation_analyzer = correlation_analyzer
        self.judge = judge
        self.order_manager = order_manager
        self.position_sizer = position_sizer
        self.state_manager = state_manager
        self.earnings_checker = earnings_checker
        self.market_data = market_data

        # State tracking
        self.current_phase = 0
        self.is_running = False
        self.last_run = None
        self.phase0_candidates = []
        self.phase1_results = []
        self.phase2_results = []
        self.phase3_decisions = []

    async def start(self) -> None:
        """Inicia o ciclo de orquestração."""
        logger.info("Iniciando IARA Orchestrator...")
        self.is_running = True

        while self.is_running:
            await self._run_cycle()

    async def stop(self) -> None:
        """Para o orquestrador de forma segura."""
        logger.info("Parando IARA Orchestrator...")
        self.is_running = False

    async def _run_cycle(self) -> None:
        """
        Executa um ciclo completo das fases com scheduling correto (WS7).

        Timing:
        - Phase 0: 08:00 (pre-market)
        - Phase 1-4: 10:30 (market open, sequencialmente)
        - Phase 5: Contínuo (runs em separate tasks)
        """
        try:
            now = datetime.now()
            hour = now.hour
            minute = now.minute

            # Phase 0: 08:00 (pre-market buzz)
            if hour == 8 and minute == 0:
                await self._phase_0_buzz_factory()

            # Phases 1-4: 10:30 (após abertura, em sequência)
            elif hour == 10 and minute == 30:
                await self._phase_1_screener()
                await self._phase_2_quant_analysis()
                await self._phase_3_judge()
                await self._phase_4_execution()

            # Sleep 5 minutos entre checks
            await asyncio.sleep(300)

        except Exception as e:
            logger.error(f"Erro no ciclo de orquestração: {e}")
            raise

    async def _phase_0_buzz_factory(self) -> List[Dict]:
        """
        FASE 0: Buzz Factory - Gera lista de oportunidades (WS7).

        Runs at 08:00 (pre-market).
        Returns: Lista de candidatos
        """
        logger.info("=" * 60)
        logger.info("FASE 0: BUZZ FACTORY - Gerando oportunidades do dia")
        logger.info("=" * 60)

        try:
            # 1. Gerar buzz candidates
            candidates = await self.buzz_factory.generate_daily_buzz()
            logger.info(f"Buzz Factory gerou {len(candidates)} candidatos brutos")

            # 2. Aplicar filtros (market cap, liquidity, Friday blocking, earnings)
            filtered = await self.buzz_factory.apply_filters(candidates)
            logger.info(f"Após filtros: {len(filtered)} candidatos válidos")

            # 3. Armazenar para Phase 1
            self.phase0_candidates = filtered

            return filtered

        except Exception as e:
            logger.error(f"Erro na Phase 0: {e}")
            return []

    async def _phase_1_screener(self) -> List[Dict]:
        """
        FASE 1: Screener - Triagem com Gemini (WS7).

        Input: phase0_candidates
        Output: Candidatos com nota >= 7
        """
        logger.info("=" * 60)
        logger.info("FASE 1: SCREENER - Triagem com IA (Gemini)")
        logger.info("=" * 60)

        try:
            if not self.phase0_candidates:
                logger.warning("Nenhum candidato da Phase 0 para processar")
                return []

            # 1. Preparar candidatos para screener
            screener_input = []
            for candidate in self.phase0_candidates:
                try:
                    # Fetch market data e technical data
                    ticker = candidate.ticker
                    data = await self.market_data.get_stock_data(ticker)

                    if not data:
                        continue

                    market_data = {
                        "ticker": ticker,
                        "price": data.price,
                        "change_pct": data.change_pct,
                        "gap_pct": getattr(data, 'gap_pct', 0)
                    }

                    # Technical analysis (simplified)
                    technical_data = {
                        "volume_ratio": getattr(data, 'volume_ratio', 1.0),
                        "rsi": 50,  # Placeholder
                        "atr": 0,
                        "supertrend_direction": "neutral"
                    }

                    screener_input.append({
                        "market_data": market_data,
                        "technical_data": technical_data,
                        "news_summary": ""
                    })

                except Exception as e:
                    logger.error(f"Erro preparando {candidate.ticker}: {e}")

            # 2. Filter duplicates (já no portfolio)
            screener_input = self.screener.filter_duplicates(screener_input, self.state_manager)
            logger.info(f"Após remover duplicatas: {len(screener_input)} candidatos")

            # 3. Run screener batch
            results = await self.screener.screen_batch(
                screener_input,
                earnings_checker=self.earnings_checker,
                max_workers=3
            )

            # 4. Filter passed (nota >= 7)
            passed = self.screener.get_passed_candidates(results)
            logger.info(f"Screener passou {len(passed)}/{len(results)} candidatos")

            self.phase1_results = passed
            return passed

        except Exception as e:
            logger.error(f"Erro na Phase 1: {e}")
            return []

    async def _phase_2_quant_analysis(self) -> List[Dict]:
        """
        FASE 2: Análise Quantitativa - The Vault (WS7).

        Aplica:
        - Correlation veto (>0.75)
        - Beta check (>3.0 sem volume = reject)
        - Sector exposure (>20% = reject)
        - Defensive mode check
        """
        logger.info("=" * 60)
        logger.info("FASE 2: THE VAULT - Análise Quantitativa")
        logger.info("=" * 60)

        try:
            if not self.phase1_results:
                logger.warning("Nenhum candidato da Phase 1 para processar")
                return []

            validated = []

            for result in self.phase1_results:
                ticker = result.ticker

                try:
                    # Fetch full data
                    import yfinance as yf
                    ticker_obj = yf.Ticker(ticker)
                    hist = ticker_obj.history(period="60d")

                    if hist.empty:
                        logger.warning(f"{ticker}: Sem dados históricos")
                        continue

                    ticker_prices = hist["Close"]

                    # 1. CORRELATION VETO (HARD)
                    portfolio_prices = {}
                    for pos in self.state_manager.get_open_positions():
                        try:
                            pos_hist = yf.Ticker(pos.ticker).history(period="60d")
                            if not pos_hist.empty:
                                portfolio_prices[pos.ticker] = pos_hist["Close"]
                        except:
                            pass

                    is_allowed, violated = self.correlation_analyzer.enforce_correlation_limit(
                        ticker, ticker_prices, portfolio_prices
                    )

                    if not is_allowed:
                        logger.warning(f"{ticker} VETADO: correlação > 0.75 com {violated}")
                        continue

                    # 2. BETA CHECK
                    spy_hist = yf.Ticker("SPY").history(period="60d")
                    risk_metrics = self.risk_calculator.calculate_risk_metrics(hist, spy_hist, ticker)
                    beta_multiplier = 1.0  # Default value

                    if risk_metrics:
                        beta = risk_metrics.beta
                        volume_ratio = getattr(result, 'volume_ratio', 1.0)

                        beta_multiplier = self.risk_calculator.calculate_beta_adjustment(beta, volume_ratio)

                        if beta_multiplier == 0.0:
                            logger.warning(f"{ticker} VETADO: Beta {beta:.2f} >= 3.0 sem volume")
                            continue

                    # 3. SECTOR EXPOSURE
                    # TODO: Calcular valor da posição estimada
                    position_value_estimate = 10000  # Placeholder
                    is_allowed_sector, sector = self.state_manager.check_sector_exposure(
                        ticker, position_value_estimate
                    )

                    if not is_allowed_sector:
                        logger.warning(f"{ticker} VETADO: Setor {sector} > 20%")
                        continue

                    # Passou em todos os checks!
                    validated.append({
                        "ticker": ticker,
                        "screener_result": result,
                        "risk_metrics": risk_metrics,
                        "beta_multiplier": beta_multiplier if risk_metrics else 1.0
                    })

                    logger.info(f"{ticker} passou Phase 2 ✅")

                except Exception as e:
                    logger.error(f"Erro processando {ticker} na Phase 2: {e}")

            logger.info(f"Phase 2 validou {len(validated)}/{len(self.phase1_results)} candidatos")
            self.phase2_results = validated
            return validated

        except Exception as e:
            logger.error(f"Erro na Phase 2: {e}")
            return []

    async def _phase_3_judge(self) -> List[Dict]:
        """FASE 3: Judge - Decisão Final com GPT (WS7)."""
        logger.info("=" * 60)
        logger.info("FASE 3: THE JUDGE - Decisão Final (GPT)")
        logger.info("=" * 60)

        try:
            if not self.phase2_results:
                logger.warning("Nenhum candidato da Phase 2")
                return []

            approved = []

            for candidate in self.phase2_results:
                ticker = candidate["ticker"]

                try:
                    # Prepare data for Judge
                    screener_result = candidate["screener_result"].__dict__
                    market_data = {"ticker": ticker, "price": 0}
                    technical_data = {}
                    macro_data = {"vix": 20, "spy_trend": "neutral"}
                    correlation_data = {"max_correlation": 0}
                    news_details = ""

                    # Get portfolio prices for correlation validation
                    portfolio_prices = {}  # TODO: fetch from positions

                    # Call Judge
                    decision = await self.judge.judge(
                        ticker, screener_result, market_data, technical_data,
                        macro_data, correlation_data, news_details,
                        correlation_analyzer=self.correlation_analyzer,
                        portfolio_prices=portfolio_prices
                    )

                    if decision.decisao == "APROVAR" and decision.nota_final >= 8:
                        approved.append({
                            "ticker": ticker,
                            "decision": decision,
                            "beta_multiplier": candidate.get("beta_multiplier", 1.0)
                        })
                        logger.info(f"{ticker} APROVADO pelo Judge (nota: {decision.nota_final})")
                    else:
                        logger.info(f"{ticker} REJEITADO pelo Judge: {decision.justificativa}")

                except Exception as e:
                    logger.error(f"Erro julgando {ticker}: {e}")

            logger.info(f"Judge aprovou {len(approved)}/{len(self.phase2_results)} candidatos")
            self.phase3_decisions = approved
            return approved

        except Exception as e:
            logger.error(f"Erro na Phase 3: {e}")
            return []

    async def _phase_4_execution(self) -> None:
        """FASE 4: Execution - Execução Armada (WS7)."""
        logger.info("=" * 60)
        logger.info("FASE 4: ARMORED EXECUTION - Execução de Ordens")
        logger.info("=" * 60)

        try:
            if not self.phase3_decisions:
                logger.info("Nenhuma decisão aprovada para executar")
                return

            for item in self.phase3_decisions:
                ticker = item["ticker"]
                decision = item["decision"]
                beta_multiplier = item.get("beta_multiplier", 1.0)

                try:
                    # 1. Check earnings proximity
                    has_earnings = self.earnings_checker.check_earnings_proximity(ticker, days=5)

                    # 2. Calculate stop loss
                    stop_loss = self.order_manager.calculate_stop_loss(
                        ticker, decision.entry_price, decision.stop_loss,  # ATR needed
                        decision.direcao, has_earnings
                    )

                    # 3. Get defensive multiplier
                    defensive_mult = self.state_manager.get_defensive_multiplier()

                    # 4. Calculate position size
                    tier = "tier1_large_cap"  # TODO: get from candidate
                    position_size = self.position_sizer.calculate(
                        self.state_manager.capital,
                        decision.entry_price,
                        stop_loss,
                        ticker,
                        tier,
                        decision.tamanho_sugerido,
                        beta_multiplier,
                        defensive_mult
                    )

                    # 5. Validate size
                    is_valid, reason = self.position_sizer.validate_size(
                        position_size,
                        len(self.state_manager.get_open_positions()),
                        0,  # TODO: calculate total exposure
                        self.state_manager.capital
                    )

                    if not is_valid:
                        logger.warning(f"{ticker} execution cancelled: {reason}")
                        continue

                    # 6. Place orders
                    logger.info(f"Executing {ticker}: {position_size.shares} shares @ ${decision.entry_price:.2f}")

                    # Entry order (STOP-LIMIT)
                    entry_order = await self.order_manager.place_entry_order(
                        ticker, decision.direcao, decision.entry_price, position_size.shares
                    )

                    # Backup stop (-10%)
                    backup_stop = decision.entry_price * 0.90

                    # Dual stop system
                    stops = await self.order_manager.place_stop_orders(
                        ticker, decision.direcao, stop_loss, backup_stop, position_size.shares
                    )

                    # Multi-target TPs
                    tps = await self.order_manager.place_take_profit_orders(
                        ticker, decision.direcao, decision.take_profit_1,
                        decision.take_profit_2, position_size.shares
                    )

                    logger.info(f"✅ {ticker} executado com sucesso")

                except Exception as e:
                    logger.error(f"Erro executando {ticker}: {e}")

        except Exception as e:
            logger.error(f"Erro na Phase 4: {e}")

    async def _phase_5_monitoring(self) -> None:
        """
        FASE 5: Monitoring - The Guardian (WS7).

        NOTE: Esta fase roda em tasks separados (watchdog, sentinel, poison_pill).
        Este método apenas documenta que Phase 5 está ativa.
        """
        logger.info("=" * 60)
        logger.info("FASE 5: THE GUARDIAN - Monitoramento Contínuo")
        logger.info("=" * 60)
        logger.info("Watchdog: Ativo (1min loop)")
        logger.info("Sentinel: Ativo (5min loop)")
        logger.info("Poison Pill: Ativo (overnight scan)")
        logger.info("=" * 60)

    def is_market_open(self) -> bool:
        """Verifica se o mercado está aberto."""
        schedule = self.config.get("schedule", {})
        now = datetime.now()

        market_open = datetime.strptime(schedule.get("market_open", "09:30"), "%H:%M").time()
        market_close = datetime.strptime(schedule.get("market_close", "16:00"), "%H:%M").time()

        return market_open <= now.time() <= market_close
