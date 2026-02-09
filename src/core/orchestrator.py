"""
ORCHESTRATOR - Maestro do Sistema IARA
Controla as Fases 0 a 5 e gerencia horarios de operacao
"""

import logging
import asyncio
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Orquestrador principal do sistema IARA.
    Coordena todas as fases do pipeline de trading.
    """

    def __init__(self, config: Dict[str, Any], buzz_factory, screener, risk_calculator,
                 correlation_analyzer, judge, order_manager, position_sizer,
                 state_manager, earnings_checker, market_data, alpaca_data=None,
                 technical_analyzer=None, macro_data=None):
        """
        Inicializa o orquestrador com TODAS as dependencias (WS7).

        Args:
            config: Configuracoes do sistema (settings.yaml)
            buzz_factory: Phase 0 - Buzz Factory
            screener: Phase 1 - Screener
            risk_calculator: Phase 2 - Risk Math
            correlation_analyzer: Phase 2 - Correlation
            judge: Phase 3 - Judge
            order_manager: Phase 4 - Order Manager
            position_sizer: Phase 4 - Position Sizer
            state_manager: State Manager
            earnings_checker: Earnings Checker
            market_data: Market Data Collector (Brain 1)
            alpaca_data: AlpacaDataCollector (Brain 2, optional)
            technical_analyzer: TechnicalAnalyzer (Phase 2/3 real indicators)
            macro_data: MacroDataCollector (real VIX, SPY, macro context)
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
        self.alpaca_data = alpaca_data  # Brain 2 (None if paper_local)
        self.technical_analyzer = technical_analyzer  # Real technical indicators
        self.macro_data = macro_data  # Real macro data (VIX, SPY, etc.)

        # Timezone from config (default Eastern)
        tz_name = config.get("schedule", {}).get("timezone", "America/New_York")
        self.tz = ZoneInfo(tz_name)

        # State tracking (protected by _pipeline_lock for async safety)
        self.current_phase = 0
        self.is_running = False
        self.last_run = None
        self.phase0_candidates = []
        self.phase1_results = []
        self.phase2_results = []
        self.phase3_decisions = []
        self._pipeline_lock = asyncio.Lock()

        # Daily execution tracking (prevents re-runs on same day)
        self._phase0_ran_today: Optional[date] = None
        self._phases_1to4_ran_today: Optional[date] = None

    def _now(self) -> datetime:
        """Returns current time in configured timezone."""
        return datetime.now(self.tz)

    async def start(self) -> None:
        """Inicia o ciclo de orquestracao com crash recovery."""
        logger.info("Iniciando IARA Orchestrator...")
        self.is_running = True

        # Log startup event
        self.state_manager.log_event("STARTUP", {
            "capital": self.state_manager.capital,
            "positions": len(self.state_manager.positions),
            "kill_switch": self.state_manager.is_kill_switch_active()
        })

        # Restore pipeline state from previous crash
        await self._restore_pipeline_state()

        while self.is_running:
            await self._run_cycle()

    async def _restore_pipeline_state(self) -> None:
        """Restaura estado do pipeline apos crash/restart.

        Problem 5: Checks phase status field. If a phase has status='running',
        it crashed mid-execution and should be re-run (its data is NOT restored).
        Only phases with status='completed' are restored.
        """
        pipeline = self.state_manager.load_pipeline_state()
        if not pipeline:
            logger.info("[PIPELINE] No pipeline state to restore (fresh day)")
            return

        last_phase = self.state_manager.get_last_completed_phase()
        logger.info(f"[PIPELINE] Restoring pipeline: last completed phase = {last_phase}")

        # Check for crashed phases (status='running')
        phases = pipeline.get("phases", {})
        for phase_str, phase_data in phases.items():
            if isinstance(phase_data, dict) and phase_data.get("status") == "running":
                logger.warning(f"[PIPELINE] Phase {phase_str} was RUNNING when system crashed "
                               f"(started at {phase_data.get('started_at', 'unknown')}) -- will re-run")

        # Helper to check if a phase is completed
        def _phase_completed(phase_num: int) -> bool:
            pd = phases.get(str(phase_num), {})
            return isinstance(pd, dict) and pd.get("status") == "completed"

        # Restore Phase 0 candidates (only if completed)
        if _phase_completed(0):
            phase0_data = self.state_manager.get_pipeline_phase_data(0)
            if phase0_data and phase0_data.get("candidates"):
                from src.collectors.buzz_factory import BuzzCandidate
                restored = []
                for c in phase0_data["candidates"]:
                    try:
                        candidate = BuzzCandidate(
                            ticker=c["ticker"],
                            source=c.get("source", "restored"),
                            buzz_score=c.get("buzz_score", 0),
                            reason=c.get("reason", "Restored from crash recovery"),
                            detected_at=datetime.now(),
                            tier=c.get("tier", "unknown"),
                            market_cap=c.get("market_cap", 0),
                            news_content=c.get("news_content", "")
                        )
                        restored.append(candidate)
                    except Exception as e:
                        logger.warning(f"[PIPELINE] Failed to restore candidate: {e}")
                self.phase0_candidates = restored
                self._phase0_ran_today = self._now().date()
                logger.info(f"[PIPELINE] Restored {len(restored)} Phase 0 candidates")

        # Restore Phase 1 results (only if completed)
        if _phase_completed(1):
            phase1_data = self.state_manager.get_pipeline_phase_data(1)
            if phase1_data and phase1_data.get("passed_tickers"):
                # Phase 1 results are ScreenerResult objects - store as lightweight refs
                from src.decision.screener import ScreenerResult
                from datetime import datetime as dt
                restored_results = []
                for r in phase1_data["results"]:
                    try:
                        sr = ScreenerResult(
                            ticker=r["ticker"],
                            nota=r.get("nota", 0),
                            resumo=r.get("resumo", ""),
                            vies=r.get("vies", "NEUTRO"),
                            confianca=r.get("confianca", 0),
                            passed=r.get("passed", False),
                            timestamp=dt.now()
                        )
                        restored_results.append(sr)
                    except Exception:
                        pass
                self.phase1_results = restored_results
                logger.info(f"[PIPELINE] Restored {len(restored_results)} Phase 1 results")

        # Restore Phase 2 results (only if completed)
        if _phase_completed(2):
            phase2_data = self.state_manager.get_pipeline_phase_data(2)
            if phase2_data and phase2_data.get("validated"):
                self.phase2_results = phase2_data["validated"]
                logger.info(f"[PIPELINE] Restored {len(self.phase2_results)} Phase 2 results")

        # Mark phases as already ran today
        if last_phase >= 0:
            self._phase0_ran_today = self._now().date()
        if last_phase >= 4:
            self._phases_1to4_ran_today = self._now().date()

        self.state_manager.log_event("PIPELINE_RESTORED", {
            "last_phase": last_phase,
            "candidates": len(self.phase0_candidates),
            "phase1_results": len(self.phase1_results),
            "phase2_results": len(self.phase2_results)
        })

    async def stop(self) -> None:
        """Para o orquestrador de forma segura."""
        logger.info("Parando IARA Orchestrator...")
        self.is_running = False
        self.state_manager.log_event("SHUTDOWN", {
            "capital": self.state_manager.capital,
            "positions": len(self.state_manager.positions),
            "phase0_candidates": len(self.phase0_candidates),
            "phase1_results": len(self.phase1_results)
        })
        self.state_manager.save_state()

    async def _run_cycle(self) -> None:
        """
        Executa um ciclo completo das fases com scheduling robusto.

        Usa window-based scheduling ao inves de exact-minute matching:
        - Phase 0: 08:00-09:25 ET (pre-market) - roda UMA vez por dia
        - Phase 1-4: 10:30-15:30 ET (market hours) - roda UMA vez por dia
        - Phase 5: Continuo (runs em separate tasks)

        Sleep entre checks: 60 segundos (garante nao perder janela).
        """
        try:
            now = self._now()
            today = now.date()
            hour = now.hour
            minute = now.minute

            # Skip weekends
            if now.weekday() >= 5:
                await asyncio.sleep(300)
                return

            # Check Kill Switch
            if self.state_manager.is_kill_switch_active():
                logger.warning("Kill Switch ativo - orchestrator pausado")
                await asyncio.sleep(60)
                return

            # Phase 0: 08:00-09:25 ET (pre-market window)
            in_phase0_window = (hour == 8) or (hour == 9 and minute <= 25)
            if in_phase0_window and self._phase0_ran_today != today:
                async with self._pipeline_lock:
                    # Re-check inside lock to prevent duplicate Phase 0 runs
                    if self._phase0_ran_today != today:
                        self._phase0_ran_today = today
                        await self._phase_0_buzz_factory()

            # Phases 1-4: 10:30-15:30 ET (after market opens, once per day)
            in_trading_window = (hour == 10 and minute >= 30) or (11 <= hour <= 15)
            has_candidates = len(self.phase0_candidates) > 0
            if in_trading_window and has_candidates and self._phases_1to4_ran_today != today:
                async with self._pipeline_lock:
                    # Smart resume: skip phases already completed today
                    last_done = self.state_manager.get_last_completed_phase()

                    if last_done < 1:
                        await self._phase_1_screener()
                    else:
                        logger.info(f"[PIPELINE] Skipping Phase 1 (already completed today)")

                    if last_done < 2:
                        await self._phase_2_quant_analysis()
                    else:
                        logger.info(f"[PIPELINE] Skipping Phase 2 (already completed today)")

                    if last_done < 3:
                        await self._phase_3_judge()
                    else:
                        logger.info(f"[PIPELINE] Skipping Phase 3 (already completed today)")

                    if last_done < 4:
                        await self._phase_4_execution()
                    else:
                        logger.info(f"[PIPELINE] Skipping Phase 4 (already completed today)")

                    # Flag set AFTER all phases complete (not before)
                    self._phases_1to4_ran_today = today

                    # Update capital history at end of cycle
                    self.state_manager.update_capital_history()

            # Log idle state (every 5 minutes to avoid spam)
            if not hasattr(self, '_last_idle_log'):
                self._last_idle_log = None
            idle_log_interval = 300  # 5 minutes
            if self._last_idle_log is None or (now - self._last_idle_log).total_seconds() >= idle_log_interval:
                self._last_idle_log = now
                # Determine why we're idle
                reasons = []
                if self._phase0_ran_today == today:
                    reasons.append(f"Phase0 done ({len(self.phase0_candidates)} candidates)")
                else:
                    if not in_phase0_window:
                        reasons.append(f"Phase0 window: 08:00-09:25 ET")
                if self._phases_1to4_ran_today == today:
                    reasons.append("Phases 1-4 done")
                elif not has_candidates:
                    reasons.append("No candidates for Phases 1-4")
                elif not in_trading_window:
                    reasons.append(f"Trading window: 10:30-15:30 ET")
                positions = len(self.state_manager.positions)
                logger.info(f"[PIPELINE] Idle at {now.strftime('%H:%M ET')} | "
                            f"{positions} positions | {' | '.join(reasons)}")

            # Sleep 60s between checks (granular enough to not miss windows)
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Erro no ciclo de orquestracao: {e}")
            await asyncio.sleep(30)

    async def _phase_0_buzz_factory(self) -> List[Dict]:
        """
        FASE 0: Buzz Factory - Gera lista de oportunidades (WS7).

        Runs at 08:00 (pre-market).
        Returns: Lista de candidatos
        """
        logger.info("=" * 60)
        logger.info("FASE 0: BUZZ FACTORY - Gerando oportunidades do dia")
        logger.info("=" * 60)

        # Mark phase as running (Problem 5: crash recovery)
        self.state_manager.mark_phase_start(0)

        try:
            # 1. Gerar buzz candidates
            candidates = await self.buzz_factory.generate_daily_buzz()
            logger.info(f"[PHASE0] Buzz Factory gerou {len(candidates)} candidatos brutos")

            # Log por fonte
            by_source = {}
            for c in candidates:
                by_source[c.source] = by_source.get(c.source, 0) + 1
            for source, count in by_source.items():
                logger.info(f"  - {source}: {count} candidatos")

            # 2. Aplicar filtros (market cap, liquidity, Friday blocking, earnings)
            filtered = await self.buzz_factory.apply_filters(candidates)
            logger.info(f"[PHASE0] Após filtros: {len(filtered)} candidatos válidos")

            # Log detalhado dos candidatos filtrados
            for c in filtered[:10]:
                has_news = "SIM" if hasattr(c, 'news_content') and c.news_content else "NAO"
                logger.info(
                    f"  [OK] {c.ticker:8s} | {c.source:15s} | score={c.buzz_score:.1f} | news={has_news}"
                )
            if len(filtered) > 10:
                logger.info(f"  ... e mais {len(filtered) - 10} candidatos")

            # 3. Armazenar para Phase 1
            self.phase0_candidates = filtered

            # 4. Persist pipeline state (crash recovery)
            candidates_data = []
            for c in filtered:
                candidates_data.append({
                    "ticker": c.ticker,
                    "source": c.source,
                    "buzz_score": c.buzz_score,
                    "reason": getattr(c, 'reason', ''),
                    "tier": getattr(c, 'tier', 'unknown'),
                    "market_cap": getattr(c, 'market_cap', 0),
                    "news_content": getattr(c, 'news_content', '')
                })
            self.state_manager.save_pipeline_state(0, {
                "candidates": candidates_data,
                "count": len(filtered)
            })
            self.state_manager.log_event("PHASE_COMPLETE", {
                "phase": 0, "candidates": len(filtered)
            })

            return filtered

        except Exception as e:
            logger.error(f"Erro na Phase 0: {e}")
            self.state_manager.log_event("PHASE_ERROR", {"phase": 0, "error": str(e)})
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

        # Mark phase as running (Problem 5: crash recovery)
        self.state_manager.mark_phase_start(1)

        try:
            if not self.phase0_candidates:
                logger.warning("Nenhum candidato da Phase 0 para processar")
                return []

            # Importar NewsAggregator para buscar notícias quando necessário
            from src.collectors.news_aggregator import NewsAggregator
            news_aggregator = NewsAggregator(self.config)

            # 1. Preparar candidatos para screener
            screener_input = []
            for candidate in self.phase0_candidates:
                try:
                    # Fetch market data e technical data
                    ticker = candidate.ticker
                    data = self.market_data.get_stock_data(ticker)

                    if not data:
                        continue

                    market_data = {
                        "ticker": ticker,
                        "price": data.price if hasattr(data, 'price') else 0,
                        "change_pct": data.change_pct if hasattr(data, 'change_pct') else 0,
                        "gap_pct": getattr(data, 'gap_pct', 0)
                    }

                    # Technical analysis - use real TechnicalAnalyzer when available
                    technical_data = {
                        "volume_ratio": getattr(data, 'volume_ratio', 1.0),
                        "rsi": 50,
                        "atr": 0,
                        "supertrend_direction": "neutral"
                    }
                    if self.technical_analyzer:
                        try:
                            hist = self.market_data.get_ohlcv(ticker, period="3mo")
                            if hist is not None and len(hist) >= 30:
                                signals = self.technical_analyzer.analyze(hist, ticker)
                                if signals:
                                    technical_data = {
                                        "volume_ratio": round(signals.volume_ratio, 2),
                                        "rsi": round(signals.rsi, 2),
                                        "atr": round(signals.atr, 2),
                                        "supertrend_direction": signals.supertrend_direction
                                    }
                        except Exception as tech_err:
                            logger.debug(f"[PHASE1] {ticker}: Technical analysis failed: {tech_err}")

                    # Buscar notícias para o candidato
                    news_summary = ""
                    if hasattr(candidate, 'news_content') and candidate.news_content:
                        # Usar notícias já coletadas na Phase 0
                        news_summary = candidate.news_content
                        logger.info(f"[PHASE1] {ticker}: Usando noticias da Phase 0 (cache hit)")
                    else:
                        # Buscar notícias fresh para candidatos sem news_content
                        try:
                            logger.info(f"[PHASE1] {ticker}: Buscando noticias (cache miss)...")
                            gnews_articles = await news_aggregator.get_gnews(ticker, max_results=3)
                            if gnews_articles:
                                # USA METODO CENTRALIZADO - mesmo formato que debug_cli
                                news_summary = news_aggregator.format_news_for_screener(ticker, gnews_articles)
                                logger.info(f"[PHASE1] {ticker}: {len(gnews_articles)} noticias formatadas para Screener")
                        except Exception as news_err:
                            logger.warning(f"[PHASE1] {ticker}: Erro buscando noticias - {news_err}")

                    screener_input.append({
                        "market_data": market_data,
                        "technical_data": technical_data,
                        "news_summary": news_summary,
                        "candidate": candidate  # Manter referência ao candidato original
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

            # 5. Persist pipeline state
            results_data = []
            for r in passed:
                results_data.append({
                    "ticker": r.ticker,
                    "nota": r.nota,
                    "resumo": r.resumo,
                    "vies": r.vies,
                    "confianca": r.confianca,
                    "passed": r.passed
                })
            self.state_manager.save_pipeline_state(1, {
                "results": results_data,
                "passed_tickers": [r.ticker for r in passed],
                "total_screened": len(results)
            })
            self.state_manager.log_event("PHASE_COMPLETE", {
                "phase": 1, "passed": len(passed), "total": len(results)
            })

            return passed

        except Exception as e:
            logger.error(f"Erro na Phase 1: {e}")
            self.state_manager.log_event("PHASE_ERROR", {"phase": 1, "error": str(e)})
            return []

    async def _phase_2_quant_analysis(self) -> List[Dict]:
        """
        FASE 2: Analise Quantitativa - The Vault.

        Aplica:
        - Correlation veto (>0.75)
        - Beta check (>3.0 sem volume = reject)
        - Sector exposure (>20% = reject)
        - Defensive mode check
        """
        logger.info("=" * 60)
        logger.info("FASE 2: THE VAULT - Analise Quantitativa")
        logger.info("=" * 60)

        # Mark phase as running (Problem 5: crash recovery)
        self.state_manager.mark_phase_start(2)

        try:
            if not self.phase1_results:
                logger.warning("Nenhum candidato da Phase 1 para processar")
                return []

            import yfinance as yf
            import asyncio

            validated = []

            # Pre-fetch SPY data once (used for all beta calculations)
            spy_hist = await asyncio.get_running_loop().run_in_executor(
                None, lambda: yf.Ticker("SPY").history(period="60d")
            )

            # Pre-fetch portfolio prices once (used for all correlation checks)
            portfolio_prices = {}
            for pos in self.state_manager.get_open_positions():
                try:
                    pos_hist = await asyncio.get_running_loop().run_in_executor(
                        None, lambda t=pos.ticker: yf.Ticker(t).history(period="60d")
                    )
                    if not pos_hist.empty:
                        portfolio_prices[pos.ticker] = pos_hist["Close"]
                except Exception:
                    pass

            for result in self.phase1_results:
                ticker = result.ticker

                try:
                    # Fetch full data (non-blocking)
                    hist = await asyncio.get_running_loop().run_in_executor(
                        None, lambda t=ticker: yf.Ticker(t).history(period="60d")
                    )

                    if hist.empty:
                        logger.warning(f"{ticker}: Sem dados historicos")
                        continue

                    ticker_prices = hist["Close"]

                    # 1. CORRELATION VETO (HARD)
                    is_allowed, violated = self.correlation_analyzer.enforce_correlation_limit(
                        ticker, ticker_prices, portfolio_prices
                    )

                    if not is_allowed:
                        logger.warning(f"{ticker} VETADO: correlacao > 0.75 com {violated}")
                        continue

                    # 2. BETA CHECK
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
                    # Use realistic stop distance for position estimate
                    # (Phase 4 uses 2.5x ATR, typical ATR is 2-5% = 5-12.5% stop)
                    risk_amount = self.state_manager.capital * self.config.get("risk", {}).get("risk_per_trade", 0.01)
                    # Estimate stop distance from hist data (ATR-based)
                    atr_estimate = hist["Close"].tail(20).std() / hist["Close"].iloc[-1] if not hist.empty else 0.03
                    stop_distance = max(0.02, atr_estimate * 2.5)
                    position_value_estimate = risk_amount / stop_distance
                    # Cap to 20% of capital (Phase 4 PositionSizer enforces this max)
                    position_value_estimate = min(position_value_estimate, self.state_manager.capital * 0.20)
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

                    logger.info(f"{ticker} passou Phase 2 [OK]")

                except Exception as e:
                    logger.error(f"Erro processando {ticker} na Phase 2: {e}")

            logger.info(f"Phase 2 validou {len(validated)}/{len(self.phase1_results)} candidatos")
            self.phase2_results = validated

            # Persist pipeline state (save serializable version)
            validated_serializable = []
            for v in validated:
                v_copy = {
                    "ticker": v["ticker"],
                    "beta_multiplier": v.get("beta_multiplier", 1.0)
                }
                # Serialize screener result
                sr = v.get("screener_result")
                if sr and hasattr(sr, '__dict__'):
                    v_copy["screener_nota"] = sr.nota if hasattr(sr, 'nota') else 0
                v_copy["has_risk_metrics"] = v.get("risk_metrics") is not None
                validated_serializable.append(v_copy)

            self.state_manager.save_pipeline_state(2, {
                "validated": validated_serializable,
                "count": len(validated)
            })
            self.state_manager.log_event("PHASE_COMPLETE", {
                "phase": 2, "validated": len(validated), "total": len(self.phase1_results)
            })

            return validated

        except Exception as e:
            logger.error(f"Erro na Phase 2: {e}")
            self.state_manager.log_event("PHASE_ERROR", {"phase": 2, "error": str(e)})
            return []

    async def _phase_3_judge(self) -> List[Dict]:
        """FASE 3: Judge - Decisão Final com GPT (WS7)."""
        logger.info("=" * 60)
        logger.info("FASE 3: THE JUDGE - Decisão Final (GPT)")
        logger.info("=" * 60)

        # Mark phase as running (Problem 5: crash recovery)
        self.state_manager.mark_phase_start(3)

        try:
            if not self.phase2_results:
                logger.warning("Nenhum candidato da Phase 2")
                return []

            import yfinance as yf

            # Importar NewsAggregator para buscar notícias detalhadas
            from src.collectors.news_aggregator import NewsAggregator
            news_aggregator = NewsAggregator(self.config)

            approved = []
            loop = asyncio.get_running_loop()

            # === PRE-FETCH SHARED DATA (once for all candidates) ===

            # 1. Real Macro Data (VIX, SPY, QQQ, DXY, 10Y) via run_in_executor
            macro_snapshot = None
            if self.macro_data:
                try:
                    macro_snapshot = await loop.run_in_executor(
                        None, self.macro_data.get_macro_snapshot
                    )
                    logger.info(
                        f"[PHASE3] Macro data: VIX={macro_snapshot.vix:.2f} "
                        f"({macro_snapshot.vix_regime.value}) | "
                        f"SPY={macro_snapshot.spy_price:.2f} ({macro_snapshot.spy_trend}) | "
                        f"QQQ={macro_snapshot.qqq_price:.2f} | "
                        f"DXY={macro_snapshot.dxy_price:.2f} | "
                        f"10Y={macro_snapshot.us10y_yield:.2f}%"
                    )
                except Exception as macro_err:
                    logger.warning(f"[PHASE3] Macro data fetch failed: {macro_err}")

            # 2. Pre-fetch portfolio prices (for correlation - non-blocking)
            portfolio_prices = {}
            for pos in self.state_manager.get_open_positions():
                try:
                    pos_hist = await loop.run_in_executor(
                        None, lambda t=pos.ticker: yf.Ticker(t).history(period="60d")
                    )
                    if not pos_hist.empty:
                        portfolio_prices[pos.ticker] = pos_hist["Close"]
                except Exception:
                    pass

            for candidate in self.phase2_results:
                ticker = candidate["ticker"]

                try:
                    # Prepare data for Judge
                    screener_result = candidate["screener_result"].__dict__

                    # Buscar dados de mercado atualizados
                    stock_data = self.market_data.get_stock_data(ticker)
                    current_price = stock_data.price if stock_data and hasattr(stock_data, 'price') else 0
                    market_data = {
                        "ticker": ticker,
                        "price": current_price,
                        "market_cap": stock_data.market_cap if stock_data and hasattr(stock_data, 'market_cap') else 0,
                        "tier": candidate.get("tier", "unknown"),
                        "beta": candidate.get("risk_metrics").beta if candidate.get("risk_metrics") else 1.0,
                        "sector_perf": 0
                    }

                    # === FETCH HISTORICAL DATA (shared by technical + correlation) ===
                    ticker_hist = None
                    try:
                        ticker_hist = await loop.run_in_executor(
                            None, lambda t=ticker: yf.Ticker(t).history(period="60d")
                        )
                    except Exception as hist_err:
                        logger.warning(f"[PHASE3] {ticker}: Historical data fetch failed: {hist_err}")

                    # === REAL TECHNICAL DATA ===
                    technical_data = {
                        "volatility_20d": 0,
                        "rsi": 50,
                        "atr": 0,
                        "supertrend_direction": "neutral",
                        "volume_ratio": 1.0,
                        "support": 0,
                        "resistance": 0
                    }
                    if self.technical_analyzer and ticker_hist is not None and not ticker_hist.empty:
                        try:
                            signals = self.technical_analyzer.analyze(ticker_hist, ticker)
                            if signals:
                                technical_data = {
                                    "volatility_20d": round(signals.atr_percent, 2),
                                    "rsi": round(signals.rsi, 2),
                                    "atr": round(signals.atr, 2),
                                    "supertrend_direction": signals.supertrend_direction,
                                    "volume_ratio": round(signals.volume_ratio, 2),
                                    "support": round(signals.support, 2),
                                    "resistance": round(signals.resistance, 2)
                                }
                                logger.info(
                                    f"[PHASE3] {ticker}: RSI={signals.rsi:.1f} | "
                                    f"ATR=${signals.atr:.2f} ({signals.atr_percent:.1f}%) | "
                                    f"ST={signals.supertrend_direction} | "
                                    f"Vol={signals.volume_ratio:.1f}x | "
                                    f"S=${signals.support:.2f} R=${signals.resistance:.2f}"
                                )
                            else:
                                logger.warning(f"[PHASE3] {ticker}: Technical analysis returned None")
                        except Exception as tech_err:
                            logger.warning(f"[PHASE3] {ticker}: Technical data failed: {tech_err}")

                    # === REAL MACRO DATA ===
                    if macro_snapshot:
                        macro_dict = {
                            "vix": macro_snapshot.vix,
                            "vix_regime": macro_snapshot.vix_regime.value,
                            "spy_trend": macro_snapshot.spy_trend,
                            "spy_price": macro_snapshot.spy_price,
                            "spy_change_pct": macro_snapshot.spy_change_pct,
                            "qqq_price": macro_snapshot.qqq_price,
                            "dxy_price": macro_snapshot.dxy_price,
                            "us10y_yield": macro_snapshot.us10y_yield
                        }
                    else:
                        logger.warning(f"[PHASE3] Using STALE macro defaults (VIX=20) - macro data unavailable")
                        macro_dict = {
                            "vix": 20, "vix_regime": "unknown",
                            "spy_trend": "neutral", "spy_price": 0,
                            "spy_change_pct": 0, "qqq_price": 0,
                            "dxy_price": 0, "us10y_yield": 0,
                            "_stale": True
                        }

                    # === REAL CORRELATION DATA ===
                    max_corr = 0.0
                    if portfolio_prices:
                        try:
                            ticker_prices = None
                            # Reuse hist if already fetched for technical analysis
                            if ticker_hist is not None and not ticker_hist.empty:
                                ticker_prices = ticker_hist["Close"]
                            else:
                                t_hist = await loop.run_in_executor(
                                    None, lambda t=ticker: yf.Ticker(t).history(period="60d")
                                )
                                if t_hist is not None and not t_hist.empty:
                                    ticker_prices = t_hist["Close"]

                            if ticker_prices is not None:
                                corr_results = self.correlation_analyzer.check_portfolio_correlation(
                                    ticker, ticker_prices, portfolio_prices
                                )
                                if corr_results:
                                    max_corr = max(abs(r.correlation) for r in corr_results)
                        except Exception as corr_err:
                            logger.warning(f"[PHASE3] {ticker}: Correlation check failed: {corr_err}")

                    sector_exposure_pct = 0
                    try:
                        exposure_by_sector = await loop.run_in_executor(
                            None, self.state_manager.get_exposure_by_sector
                        )
                        total_exposure = sum(exposure_by_sector.values())
                        if total_exposure > 0 and self.state_manager.capital > 0:
                            sector_exposure_pct = (total_exposure / self.state_manager.capital) * 100
                    except Exception:
                        pass

                    correlation_data = {
                        "max_correlation": round(max_corr, 3),
                        "sector_exposure": round(sector_exposure_pct, 1)
                    }

                    # Buscar noticias DETALHADAS para o Judge
                    # Strategy 1: Gemini + Google Search grounding (real article content)
                    # Strategy 2: GNews RSS fallback (titles/summaries only)
                    news_details = ""
                    try:
                        logger.info(f"[PHASE3] {ticker}: Buscando noticias via Google Search grounding...")
                        news_details = await news_aggregator.get_news_digest_grounded(ticker)
                        if news_details:
                            logger.info(f"[PHASE3] {ticker}: Got grounded news digest ({len(news_details)} chars)")
                    except Exception as e:
                        logger.warning(f"[PHASE3] {ticker}: Grounding failed: {e}")

                    # Fallback to GNews if grounding returned nothing
                    if not news_details:
                        try:
                            logger.info(f"[PHASE3] {ticker}: Fallback - buscando via GNews RSS...")
                            gnews_articles = await news_aggregator.get_gnews(
                                ticker, max_results=8, fetch_full_content=True
                            )
                            if gnews_articles:
                                news_details = news_aggregator.format_news_for_judge(ticker, gnews_articles)
                                logger.info(
                                    f"[PHASE3] {ticker}: {len(gnews_articles)} noticias GNews (fallback) | "
                                    f"Best score: {gnews_articles[0].get('relevance_score', 0):.1f}"
                                )
                            else:
                                news_details = f"No recent news found for {ticker}"
                                logger.info(f"[PHASE3] {ticker}: Nenhuma noticia recente encontrada")
                        except Exception as news_err:
                            logger.warning(f"[PHASE3] {ticker}: GNews fallback also failed - {news_err}")
                            news_details = "News fetch failed"

                    # BRAIN 2: Fetch Alpaca real-time data (if available)
                    alpaca_text = ""
                    coherence_text = ""
                    if self.alpaca_data and self.alpaca_data.available:
                        try:
                            logger.info(f"[PHASE3] {ticker}: Brain 2 - Fetching Alpaca real-time data...")

                            # Real-time snapshot
                            snapshot = await self.alpaca_data.get_realtime_snapshot(ticker)

                            # Alpaca news (Benzinga)
                            alpaca_news = await self.alpaca_data.get_news(ticker, limit=5)

                            # Data coherence check (Brain 1 vs Brain 2)
                            yf_price = market_data.get("price", 0)
                            coherence = await self.alpaca_data.compare_with_yfinance(ticker, yf_price)

                            # Format for Judge
                            if snapshot or alpaca_news:
                                alpaca_text = self.alpaca_data.format_for_judge(
                                    snapshot or {}, alpaca_news, coherence or {}
                                )
                                logger.info(f"[PHASE3] {ticker}: Brain 2 data ready "
                                            f"(spread={snapshot.get('spread_pct', 0):.3f}%, "
                                            f"news={len(alpaca_news)})")

                            if coherence:
                                agrees = coherence.get("data_agrees", True)
                                diff = coherence.get("price_diff_pct", 0)
                                coherence_text = (
                                    f"Brain 1 (yfinance) price: ${yf_price:.2f} | "
                                    f"Brain 2 (Alpaca) price: ${coherence.get('alpaca_price', 0):.2f} | "
                                    f"Diff: {diff:.2f}% | "
                                    f"{'CONCORDAM' if agrees else 'DIVERGEM (cautela!)'}"
                                )

                        except Exception as alpaca_err:
                            logger.warning(f"[PHASE3] {ticker}: Brain 2 error - {alpaca_err}")

                    # Warn Judge if macro data is stale
                    if macro_dict.get("_stale"):
                        stale_warning = "WARNING: Macro data UNAVAILABLE - VIX/SPY values are DEFAULT estimates. Reduce confidence in macro-dependent analysis."
                        if coherence_text:
                            coherence_text += f"\n{stale_warning}"
                        else:
                            coherence_text = stale_warning

                    # Call Judge com DUAL BRAIN data + REAL indicators
                    decision = await self.judge.judge(
                        ticker, screener_result, market_data, technical_data,
                        macro_dict, correlation_data, news_details,
                        correlation_analyzer=self.correlation_analyzer,
                        portfolio_prices=portfolio_prices,
                        alpaca_data=alpaca_text,
                        data_coherence=coherence_text
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

            # Persist pipeline state
            decisions_data = []
            for item in approved:
                d = item["decision"]
                decisions_data.append({
                    "ticker": item["ticker"],
                    "decisao": d.decisao,
                    "nota_final": d.nota_final,
                    "direcao": d.direcao,
                    "entry_price": d.entry_price,
                    "stop_loss": d.stop_loss,
                    "take_profit_1": d.take_profit_1,
                    "take_profit_2": d.take_profit_2,
                    "risco_recompensa": d.risco_recompensa,
                    "tamanho_sugerido": d.tamanho_sugerido,
                    "beta_multiplier": item.get("beta_multiplier", 1.0)
                })
            self.state_manager.save_pipeline_state(3, {
                "decisions": decisions_data,
                "approved_count": len(approved)
            })
            self.state_manager.log_event("PHASE_COMPLETE", {
                "phase": 3, "approved": len(approved),
                "tickers": [a["ticker"] for a in approved]
            })

            return approved

        except Exception as e:
            logger.error(f"Erro na Phase 3: {e}")
            self.state_manager.log_event("PHASE_ERROR", {"phase": 3, "error": str(e)})
            return []

    async def _phase_4_execution(self) -> None:
        """FASE 4: Execution - Execução Armada (WS7)."""
        logger.info("=" * 60)
        logger.info("FASE 4: ARMORED EXECUTION - Execução de Ordens")
        logger.info("=" * 60)

        # Mark phase as running (Problem 5: crash recovery)
        self.state_manager.mark_phase_start(4)

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

                    # 4. Calculate position size (dynamic tier)
                    stock_data = self.market_data.get_stock_data(ticker)
                    market_cap = stock_data.market_cap if stock_data and hasattr(stock_data, 'market_cap') else 0
                    tier = "tier1_large_cap" if market_cap >= 4_000_000_000 else "tier2_mid_cap"
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

                    # 5. Validate size (calculate real exposure)
                    positions = self.state_manager.get_open_positions()
                    total_exposure = sum(p.entry_price * p.quantity for p in positions)
                    is_valid, reason = self.position_sizer.validate_size(
                        position_size,
                        len(positions),
                        total_exposure,
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

                    logger.info(f"[OK] {ticker} executado com sucesso")
                    self.state_manager.log_event("TRADE_EXECUTED", {
                        "ticker": ticker,
                        "direction": decision.direcao,
                        "entry_price": decision.entry_price,
                        "stop_loss": stop_loss,
                        "shares": position_size.shares
                    })

                except Exception as e:
                    logger.error(f"Erro executando {ticker}: {e}")
                    self.state_manager.log_event("TRADE_ERROR", {
                        "ticker": ticker, "error": str(e)
                    })

            # Persist pipeline complete
            self.state_manager.save_pipeline_state(4, {
                "executed_tickers": [item["ticker"] for item in self.phase3_decisions],
                "completed_at": datetime.now().isoformat()
            })
            self.state_manager.log_event("PHASE_COMPLETE", {"phase": 4})

        except Exception as e:
            logger.error(f"Erro na Phase 4: {e}")
            self.state_manager.log_event("PHASE_ERROR", {"phase": 4, "error": str(e)})

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
        """Verifica se o mercado esta aberto (timezone-aware, skip weekends)."""
        now = self._now()

        # Weekends are closed
        if now.weekday() >= 5:
            return False

        schedule = self.config.get("schedule", {})
        market_open = datetime.strptime(schedule.get("market_open", "09:30"), "%H:%M").time()
        market_close = datetime.strptime(schedule.get("market_close", "16:00"), "%H:%M").time()

        return market_open <= now.time() <= market_close

    async def run_full_pipeline(self, force: bool = False) -> Dict[str, Any]:
        """
        Executa pipeline completo Phase 0-4 de uma vez (para testes e debug).

        Args:
            force: Se True, ignora verificacoes de horario

        Returns:
            Dict com resultados de cada fase
        """
        results: Dict[str, Any] = {
            "phase0_candidates": 0,
            "phase1_passed": 0,
            "phase2_validated": 0,
            "phase3_approved": 0,
            "phase4_executed": 0,
            "errors": []
        }

        try:
            # Phase 0
            candidates = await self._phase_0_buzz_factory()
            results["phase0_candidates"] = len(candidates) if candidates else 0

            if not candidates:
                results["errors"].append("Phase 0 returned no candidates")
                return results

            # Phase 1
            passed = await self._phase_1_screener()
            results["phase1_passed"] = len(passed) if passed else 0

            if not passed:
                results["errors"].append("Phase 1 filtered all candidates")
                return results

            # Phase 2
            validated = await self._phase_2_quant_analysis()
            results["phase2_validated"] = len(validated) if validated else 0

            if not validated:
                results["errors"].append("Phase 2 vetoed all candidates")
                return results

            # Phase 3
            approved = await self._phase_3_judge()
            results["phase3_approved"] = len(approved) if approved else 0

            if not approved:
                results["errors"].append("Phase 3 rejected all candidates")
                return results

            # Phase 4
            await self._phase_4_execution()
            results["phase4_executed"] = len(self.phase3_decisions)

        except Exception as e:
            results["errors"].append(str(e))
            logger.error(f"Pipeline error: {e}")

        return results
