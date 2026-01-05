"""
Test script para verificar todos os imports do sistema IARA
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("TESTE 1: Verificando Imports do Sistema IARA")
print("=" * 60)

# Test Phase 0
print("\n[Phase 0] Buzz Factory...")
try:
    from src.collectors.buzz_factory import BuzzFactory, BuzzCandidate
    from src.collectors.news_aggregator import NewsAggregator, NewsArticle
    from src.collectors.earnings_checker import EarningsChecker
    print("[OK] Phase 0 imports OK")
except Exception as e:
    print(f"[ERROR] Phase 0 error: {e}")
    sys.exit(1)

# Test Phase 1
print("\n[Phase 1] Screener...")
try:
    from src.decision.screener import Screener, ScreenerResult
    from src.analysis.technical import TechnicalAnalyzer, TechnicalSignals
    print("[OK] Phase 1 imports OK")
except Exception as e:
    print(f"[ERROR] Phase 1 error: {e}")
    sys.exit(1)

# Test Phase 2
print("\n[Phase 2] Risk Math...")
try:
    from src.analysis.risk_math import RiskCalculator, RiskMetrics
    from src.analysis.correlation import CorrelationAnalyzer, CorrelationResult
    print("[OK] Phase 2 imports OK")
except Exception as e:
    print(f"[ERROR] Phase 2 error: {e}")
    sys.exit(1)

# Test Phase 3
print("\n[Phase 3] Judge...")
try:
    from src.decision.judge import Judge, TradeDecision
    from src.decision.grounding import GroundingService, GroundingResult
    from src.decision.ai_gateway import AIGateway, AIProvider
    print("[OK] Phase 3 imports OK")
except Exception as e:
    print(f"[ERROR] Phase 3 error: {e}")
    sys.exit(1)

# Test Phase 4
print("\n[Phase 4] Execution...")
try:
    from src.execution.order_manager import OrderManager, Order, OrderType
    from src.execution.position_sizer import PositionSizer, PositionSize
    print("[OK] Phase 4 imports OK")
except Exception as e:
    print(f"[ERROR] Phase 4 error: {e}")
    sys.exit(1)

# Test Phase 5
print("\n[Phase 5] Monitoring...")
try:
    from src.monitoring.watchdog import Watchdog, PriceAlert
    from src.monitoring.sentinel import Sentinel, NewsAlert
    print("[OK] Phase 5 imports OK")
except Exception as e:
    print(f"[ERROR] Phase 5 error: {e}")
    sys.exit(1)

# Test Core
print("\n[Core] Orchestrator & State...")
try:
    from src.core.orchestrator import Orchestrator
    from src.core.state_manager import StateManager, Position
    from src.core.database import Database
    print("[OK] Core imports OK")
except Exception as e:
    print(f"[ERROR] Core error: {e}")
    sys.exit(1)

# Test Debug
print("\n[Debug] Debug CLI...")
try:
    from src.debug.debug_commands import DebugCommands
    print("[OK] Debug imports OK")
except Exception as e:
    print(f"[ERROR] Debug error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("[OK] TODOS OS IMPORTS PASSARAM!")
print("=" * 60)
print("\nSistema IARA pronto para testes funcionais.")
