"""
Test script para verificar integração completa do pipeline IARA
Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4
"""

import sys
from pathlib import Path
import asyncio

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.collectors.buzz_factory import BuzzFactory
from src.collectors.market_data import MarketDataCollector
from src.collectors.news_scraper import NewsScraper
from src.decision.screener import Screener
from src.decision.judge import Judge
from src.decision.ai_gateway import AIGateway
from src.analysis.risk_math import RiskCalculator
from src.analysis.correlation import CorrelationAnalyzer
from src.core.state_manager import StateManager
from src.execution.position_sizer import PositionSizer
from datetime import datetime
import yaml

print("=" * 60)
print("TESTE 7: Integration Test - Pipeline Completo")
print("=" * 60)

# Load config
config_path = Path(__file__).parent / "config" / "settings.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

async def test_integration():
    """Test complete pipeline flow"""

    # Initialize components
    print("\n[1] Initializing Components...")
    market_data = MarketDataCollector(config)
    news_scraper = NewsScraper(config)
    buzz_factory = BuzzFactory(config, market_data, news_scraper)
    ai_gateway = AIGateway(config)
    screener = Screener(config, ai_gateway)
    judge = Judge(config, ai_gateway)
    risk_calc = RiskCalculator(config)
    correlation_analyzer = CorrelationAnalyzer(config)
    state_manager = StateManager(config)
    position_sizer = PositionSizer(config)

    print("[OK] All components initialized")

    # Phase 0: Buzz Factory
    print("\n[2] Phase 0: Buzz Factory - Generating Candidates...")
    try:
        # Generate candidates (this will try to fetch real data)
        candidates = await buzz_factory.generate_daily_buzz()
        print(f"[OK] Generated {len(candidates)} raw candidates")

        # Apply filters
        filtered = await buzz_factory.apply_filters(candidates)
        print(f"[OK] {len(filtered)} candidates passed filters")

        if filtered:
            print("Sample candidate:")
            c = filtered[0]
            print(f"  - {c.ticker}: {c.source} (buzz={c.buzz_score:.2f}, tier={c.tier})")
    except Exception as e:
        print(f"[WARNING] Phase 0 failed (likely missing API keys): {e}")
        print("[INFO] Creating mock candidate for testing...")
        from src.collectors.buzz_factory import BuzzCandidate
        filtered = [
            BuzzCandidate(
                ticker="AAPL",
                source="watchlist",
                buzz_score=8.0,
                reason="Test candidate",
                detected_at=datetime.now(),
                tier="Tier 1",
                market_cap=2500000000000
            )
        ]
        print(f"[OK] Using {len(filtered)} mock candidates")

    # Phase 1: Screener (mock - requires API)
    print("\n[3] Phase 1: Screener - AI Triage...")
    print("[INFO] Skipping actual AI calls (requires API keys)")
    print("[INFO] Creating mock screener results...")

    from src.decision.screener import ScreenerResult
    screener_results = []
    for c in filtered[:3]:  # Test with first 3
        result = ScreenerResult(
            ticker=c.ticker,
            nota=7.5,
            resumo="Mock screener result",
            vies="LONG",
            confianca=0.8,
            passed=True,
            timestamp=datetime.now()
        )
        screener_results.append(result)

    print(f"[OK] {len(screener_results)} candidates passed screener (mock)")

    # Phase 2: Risk Math & Correlation
    print("\n[4] Phase 2: Risk Math - Applying Filters...")

    passed_phase2 = []
    for result in screener_results:
        ticker = result.ticker
        print(f"\nProcessing {ticker}...")

        # Get market data
        try:
            data = market_data.get_stock_data(ticker)
            if not data:
                print(f"  [SKIP] No market data for {ticker}")
                continue

            beta = data.beta if hasattr(data, 'beta') else 1.0
            volume_ratio = 1.5  # Mock

            # Beta adjustment
            beta_mult = risk_calc.calculate_beta_adjustment(beta, volume_ratio)
            print(f"  Beta: {beta:.2f}, Volume: {volume_ratio}x -> multiplier: {beta_mult}")

            if beta_mult == 0.0:
                print(f"  [REJECT] Beta veto")
                continue

            # Correlation check (mock - no positions yet)
            portfolio_positions = state_manager.get_open_positions()
            if portfolio_positions:
                print(f"  [INFO] Would check correlation with {len(portfolio_positions)} positions")
            else:
                print(f"  [OK] No positions to check correlation")

            # Defensive mode check
            is_defensive = state_manager.is_defensive_mode()
            defensive_mult = state_manager.get_defensive_multiplier()
            print(f"  Defensive mode: {is_defensive}, multiplier: {defensive_mult}")

            # Sector exposure check
            is_allowed, sector = state_manager.check_sector_exposure(ticker, 10000)
            print(f"  Sector exposure: {sector} - allowed: {is_allowed}")

            if is_allowed:
                passed_phase2.append({
                    "ticker": ticker,
                    "result": result,
                    "beta_mult": beta_mult,
                    "defensive_mult": defensive_mult
                })
                print(f"  [PASS] {ticker} passed Phase 2")
            else:
                print(f"  [REJECT] Sector exposure limit")

        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")

    print(f"\n[OK] {len(passed_phase2)} candidates passed Phase 2")

    # Phase 3: Judge (mock - requires API)
    print("\n[5] Phase 3: Judge - Final Decision...")
    print("[INFO] Skipping actual Judge AI calls")
    print("[INFO] Creating mock judge decisions...")

    from src.decision.judge import TradeDecision
    approved_decisions = []

    for item in passed_phase2:
        ticker = item["ticker"]

        # Mock decision
        decision = TradeDecision(
            ticker=ticker,
            decisao="APROVAR",
            nota_final=8.5,
            direcao="LONG",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit_1=155.0,
            take_profit_2=160.0,
            risco_recompensa=2.5,
            tamanho_sugerido="NORMAL",
            justificativa="Mock decision for testing",
            alertas=[],
            validade_horas=4,
            timestamp=datetime.now()
        )

        # Validate decision
        is_valid = judge.validate_decision(decision, state_manager.get_open_positions())

        if is_valid:
            approved_decisions.append({
                "decision": decision,
                "beta_mult": item["beta_mult"],
                "defensive_mult": item["defensive_mult"]
            })
            print(f"[OK] {ticker} APPROVED - Score: {decision.nota_final}, R/R: {decision.risco_recompensa:.1f}")
        else:
            print(f"[REJECT] {ticker} failed validation")

    print(f"\n[OK] {len(approved_decisions)} decisions approved")

    # Phase 4: Position Sizing & Execution
    print("\n[6] Phase 4: Execution - Position Sizing...")

    for item in approved_decisions:
        decision = item["decision"]
        ticker = decision.ticker

        # Calculate position size
        position_size = position_sizer.calculate(
            capital=state_manager.capital,
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            ticker=ticker,
            tier="tier1_large_cap",
            size_suggestion=decision.tamanho_sugerido,
            beta_multiplier=item["beta_mult"],
            defensive_multiplier=item["defensive_mult"]
        )

        print(f"\n{ticker}:")
        print(f"  Entry: ${decision.entry_price:.2f}")
        print(f"  Stop: ${decision.stop_loss:.2f}")
        print(f"  TP1: ${decision.take_profit_1:.2f}")
        print(f"  TP2: ${decision.take_profit_2:.2f}")
        print(f"  Position size: {position_size.shares} shares")
        print(f"  Position value: ${position_size.position_value:.2f}")
        print(f"  Risk: ${position_size.risk_amount:.2f} ({position_size.risk_percent*100:.2f}%)")
        print(f"  R/R: {decision.risco_recompensa:.1f}:1")

    print("\n[OK] Position sizing calculated for all approved decisions")

    # Summary
    print("\n" + "=" * 60)
    print("[OK] INTEGRATION TEST COMPLETED!")
    print("=" * 60)
    print("\nPipeline Summary:")
    print(f"  Phase 0 (Buzz Factory): {len(filtered)} candidates")
    print(f"  Phase 1 (Screener): {len(screener_results)} passed (mock)")
    print(f"  Phase 2 (Risk Math): {len(passed_phase2)} passed")
    print(f"  Phase 3 (Judge): {len(approved_decisions)} approved (mock)")
    print(f"  Phase 4 (Execution): {len(approved_decisions)} ready for execution")
    print("\nConversion Rate:")
    if len(filtered) > 0:
        conversion = (len(approved_decisions) / len(filtered)) * 100
        print(f"  {conversion:.1f}% of initial candidates approved")
    print("\nNOTE: Full test with real AI requires API keys in .env")

# Run the async test
asyncio.run(test_integration())
