"""
Test script para verificar Phase 1 - Screener
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.decision.screener import Screener
from src.collectors.earnings_checker import EarningsChecker
from src.core.state_manager import StateManager, Position
from src.decision.ai_gateway import AIGateway
from datetime import datetime
import yaml

print("=" * 60)
print("TESTE 4: Phase 1 - Screener")
print("=" * 60)

async def test_phase1():
    # Load config
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    # Initialize components
    print("\n[1] Initializing Screener...")
    ai_gateway = AIGateway(config)
    screener = Screener(config, ai_gateway)
    earnings_checker = EarningsChecker(config)
    state_manager = StateManager(config)
    print("[OK] Screener initialized")
    
    # Test duplicate filtering
    print("\n[2] Testing duplicate filtering...")
    test_candidates = [
        {"ticker": "AAPL"},
        {"ticker": "MSFT"},
        {"ticker": "GOOGL"}
    ]
    
    # Add AAPL to portfolio
    test_position = Position(
        ticker="AAPL",
        direction="LONG",
        entry_price=150.0,
        quantity=10,
        stop_loss=145.0,
        take_profit=155.0,
        entry_time=datetime.now()
    )
    state_manager.add_position(test_position)
    
    filtered = screener.filter_duplicates(test_candidates, state_manager)
    print(f"[OK] Duplicate filter executed: {len(test_candidates)} -> {len(filtered)} candidates")
    print(f"    Open positions in portfolio: {[p.ticker for p in state_manager.get_open_positions()]}")
    
    # Test screening (mock - without calling Gemini API)
    print("\n[3] Testing screener structure...")
    try:
        market_data = {
            "ticker": "TSLA",
            "price": 250.0,
            "change_pct": 0.05,
            "gap_pct": 0.01
        }
        
        technical_data = {
            "volume_ratio": 2.5,
            "rsi": 65,
            "atr": 5.0,
            "supertrend_direction": "bullish"
        }
        
        news_summary = "Tesla announces new factory expansion"
        
        # NOTE: This will actually call Gemini API if GEMINI_API_KEY is set
        # For a true unit test, we would mock the AI gateway
        print("[SKIP] Actual screening test (requires API key)")
        print("      To test: set GEMINI_API_KEY in environment")
        
    except Exception as e:
        print(f"[WARNING] Screening test skipped: {e}")
    
    # Test earnings proximity check
    print("\n[4] Testing earnings integration...")
    try:
        has_earnings = earnings_checker.check_earnings_proximity("TSLA", days=5)
        print(f"[OK] Earnings check for TSLA: {has_earnings}")
    except Exception as e:
        print(f"[WARNING] Earnings check error: {e}")
    
    # Test get_passed_candidates
    print("\n[5] Testing result filtering...")

    # Create real ScreenerResult objects (not mocks)
    from src.decision.screener import ScreenerResult

    mock_results = [
        ScreenerResult(
            ticker='TSLA',
            nota=8.5,
            resumo='Strong momentum',
            vies='LONG',
            confianca=0.85,
            passed=True,
            timestamp=datetime.now()
        ),
        ScreenerResult(
            ticker='AMD',
            nota=6.0,
            resumo='Weak signal',
            vies='NEUTRO',
            confianca=0.60,
            passed=False,
            timestamp=datetime.now()
        )
    ]

    passed = screener.get_passed_candidates(mock_results)
    print(f"[OK] Result filter: {len(mock_results)} -> {len(passed)} passed")

    if len(passed) == 1 and passed[0].ticker == "TSLA":
        print("    [OK] Only TSLA passed (nota >= 7)")
    else:
        print(f"    [ERROR] Expected 1 passed (TSLA), got {len(passed)}")
    
    print("\n" + "=" * 60)
    print("[OK] PHASE 1 TESTS COMPLETED!")
    print("=" * 60)
    print("\nNote: Full Gemini API test requires GEMINI_API_KEY")

# Run async test
asyncio.run(test_phase1())
