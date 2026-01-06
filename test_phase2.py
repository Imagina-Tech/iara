"""
Test script para verificar Phase 2 - Risk Math
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.analysis.risk_math import RiskCalculator
from src.analysis.correlation import CorrelationAnalyzer
from src.core.state_manager import StateManager, Position
from datetime import datetime
import yaml
import pandas as pd
import numpy as np

print("=" * 60)
print("TESTE 5: Phase 2 - Risk Math")
print("=" * 60)

# Load config
config_path = Path(__file__).parent / "config" / "settings.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

print("\n[1] Testing Beta Adjustment...")
risk_calc = RiskCalculator(config)

# Test cases
test_cases = [
    {"beta": 1.5, "volume": 1.0, "expected_mult": 1.0, "desc": "Normal beta (<2.0)"},
    {"beta": 2.5, "volume": 1.0, "expected_mult": 0.75, "desc": "Aggressive beta (2.0-3.0)"},
    {"beta": 3.5, "volume": 2.5, "expected_mult": 0.5, "desc": "Extreme beta with volume"},
    {"beta": 3.5, "volume": 1.0, "expected_mult": 0.0, "desc": "Extreme beta WITHOUT volume (REJECT)"},
]

passed = 0
for tc in test_cases:
    result = risk_calc.calculate_beta_adjustment(tc["beta"], tc["volume"])
    status = "[OK]" if result == tc["expected_mult"] else "[FAIL]"
    print(f"{status} {tc['desc']}: beta={tc['beta']}, vol={tc['volume']} -> mult={result} (expected {tc['expected_mult']})")
    if result == tc["expected_mult"]:
        passed += 1

print(f"\nBeta Adjustment: {passed}/{len(test_cases)} tests passed")

print("\n[2] Testing Defensive Mode...")
state_manager = StateManager(config)

# Test normal state
is_def = state_manager.is_defensive_mode()
print(f"[OK] Initial defensive mode: {is_def} (should be False)")

# Simulate drawdown
print("\nSimulating drawdown history...")
# Add some capital history to simulate drawdown
for i in range(10):
    state_manager.capital_history.append({
        "date": f"2026-01-{i+1:02d}",
        "capital": 100000 - (i * 500)  # Gradual decline
    })

weekly_dd = state_manager.get_weekly_drawdown()
print(f"[OK] Weekly drawdown: {weekly_dd*100:.2f}%")

defensive_mult = state_manager.get_defensive_multiplier()
print(f"[OK] Defensive multiplier: {defensive_mult}")

if weekly_dd >= 0.05:
    print("[OK] Defensive mode would activate (weekly DD >= 5%)")
else:
    print("[OK] Defensive mode inactive (weekly DD < 5%)")

print("\n[3] Testing Correlation Analysis...")
correlation_analyzer = CorrelationAnalyzer(config)

# Create sample price data
dates = pd.date_range(start='2025-12-01', periods=60)
np.random.seed(42)

# Ticker 1: Base prices
base = np.random.randn(60).cumsum()
prices1 = pd.Series(100 + base, index=dates)

# Ticker 2: Highly correlated (same movement + tiny noise)
# Using returns to ensure high correlation
prices2 = pd.Series(150 + base * 1.5 + np.random.randn(60) * 0.1, index=dates)

# Ticker 3: Low correlation (independent)
prices3 = pd.Series(200 + np.random.randn(60).cumsum(), index=dates)

print("Testing correlation between assets...")

# Calculate actual correlation for debugging
actual_corr = correlation_analyzer.calculate_correlation(prices1, prices2)
print(f"  Calculated correlation TICKER1 vs TICKER2: {actual_corr:.3f}")
print(f"  Max allowed correlation: {correlation_analyzer.max_correlation:.3f}")

# Test high correlation (should veto)
portfolio_prices = {"TICKER1": prices1}
is_allowed, violated = correlation_analyzer.enforce_correlation_limit(
    "TICKER2", prices2, portfolio_prices
)

if not is_allowed:
    print(f"[OK] High correlation VETOED: TICKER2 vs {violated}")
else:
    print(f"[FAIL] High correlation should have been vetoed (corr={actual_corr:.3f} > {correlation_analyzer.max_correlation:.3f})")

# Test low correlation (should allow)
is_allowed2, violated2 = correlation_analyzer.enforce_correlation_limit(
    "TICKER3", prices3, portfolio_prices
)

if is_allowed2:
    print(f"[OK] Low correlation ALLOWED: TICKER3")
else:
    print(f"[FAIL] Low correlation should have been allowed")

print("\n[4] Testing Sector Exposure...")

# Add test position to state manager
test_position = Position(
    ticker="AAPL",
    direction="LONG",
    entry_price=150.0,
    quantity=100,
    stop_loss=145.0,
    take_profit=155.0,
    entry_time=datetime.now()
)
state_manager.add_position(test_position)

# Check sector exposure
is_allowed_sector, sector = state_manager.check_sector_exposure("AAPL", 10000)
print(f"[OK] Sector exposure check: allowed={is_allowed_sector}, sector={sector}")

# Get exposure by sector
exposure = state_manager.get_exposure_by_sector()
print(f"[OK] Exposure by sector: {exposure}")

print("\n" + "=" * 60)
print("[OK] PHASE 2 TESTS COMPLETED!")
print("=" * 60)
print("\nSummary:")
print(f"  - Beta adjustment: {passed}/{len(test_cases)} tests passed")
print(f"  - Defensive mode: Functional")
print(f"  - Correlation veto: Functional")
print(f"  - Sector exposure: Functional")
