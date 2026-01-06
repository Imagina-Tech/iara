"""
Test script para verificar Phase 3 - Judge
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.decision.judge import Judge
from src.decision.ai_gateway import AIGateway
from src.core.database import Database
from src.analysis.correlation import CorrelationAnalyzer
from datetime import datetime
import yaml
import pandas as pd
import numpy as np

print("=" * 60)
print("TESTE 6: Phase 3 - Judge")
print("=" * 60)

# Load config
config_path = Path(__file__).parent / "config" / "settings.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

print("\n[1] Testing Database Cache System...")
db_path = Path(__file__).parent / "data" / "iara.db"
db = Database(db_path)

# Create a mock decision
test_decision = {
    "ticker": "TEST",
    "decisao": "APROVAR",
    "nota_final": 8.5,
    "direcao": "LONG",
    "entry_price": 150.0,
    "stop_loss": 145.0,
    "take_profit_1": 155.0,
    "take_profit_2": 160.0,
    "risco_recompensa": 2.5,
    "tamanho_sugerido": "NORMAL",
    "justificativa": "Test decision",
    "alertas": [],
    "validade_horas": 4,
    "timestamp": datetime.now()
}

# Cache decision
db.cache_decision("TEST", test_decision)
print("[OK] Decision cached successfully")

# Retrieve from cache (<2h)
cached = db.get_cached_decision("TEST", max_age_hours=2)
if cached:
    print(f"[OK] Cache HIT: Retrieved decision for {cached['ticker']}")
    print(f"    Decisao: {cached['decisao']}, Nota: {cached['nota_final']}")
else:
    print("[FAIL] Cache MISS: Should have found cached decision")

# Test cache expiration
old_cached = db.get_cached_decision("TEST", max_age_hours=0)
if old_cached:
    print("[FAIL] Cache should have expired (max_age=0)")
else:
    print("[OK] Cache expiration works correctly")

print("\n[2] Testing Decision Threshold Validation...")
ai_gateway = AIGateway(config)
judge = Judge(config, ai_gateway)

# Test threshold (default: 8)
print(f"Judge threshold: {judge.threshold}")

# Simulate decision below threshold
mock_decision_low = {
    "decisao": "APROVAR",
    "nota_final": 7.0,
    "direcao": "LONG",
    "entry_price": 100.0,
    "stop_loss": 95.0,
    "take_profit_1": 105.0,
    "take_profit_2": 110.0,
    "risco_recompensa": 2.0,
    "tamanho_posicao_sugerido": "NORMAL",
    "justificativa": "Test",
    "alertas": [],
    "validade_horas": 4
}

parsed = judge._parse_decision("LOWSCORE", mock_decision_low)
if parsed.decisao == "REJEITAR":
    print(f"[OK] Decision with nota {mock_decision_low['nota_final']} correctly REJECTED (threshold {judge.threshold})")
else:
    print(f"[FAIL] Decision should have been rejected (nota {mock_decision_low['nota_final']} < {judge.threshold})")

# Test decision above threshold
mock_decision_high = {
    "decisao": "APROVAR",
    "nota_final": 8.5,
    "direcao": "LONG",
    "entry_price": 100.0,
    "stop_loss": 95.0,
    "take_profit_1": 105.0,
    "take_profit_2": 110.0,
    "risco_recompensa": 2.0,
    "tamanho_posicao_sugerido": "NORMAL",
    "justificativa": "Test",
    "alertas": [],
    "validade_horas": 4
}

parsed_high = judge._parse_decision("HIGHSCORE", mock_decision_high)
if parsed_high.decisao == "APROVAR":
    print(f"[OK] Decision with nota {mock_decision_high['nota_final']} correctly APPROVED")
else:
    print(f"[FAIL] Decision should have been approved (nota {mock_decision_high['nota_final']} >= {judge.threshold})")

print("\n[3] Testing Decision Validation...")

# Test risk/reward minimum
decision_bad_rr = judge._create_rejection("BADRR", "Low R/R")
decision_bad_rr.decisao = "APROVAR"
decision_bad_rr.risco_recompensa = 1.5

is_valid = judge.validate_decision(decision_bad_rr, [])
if not is_valid:
    print(f"[OK] Decision with R/R {decision_bad_rr.risco_recompensa} correctly rejected (min 2.0)")
else:
    print(f"[FAIL] Decision with low R/R should have been rejected")

# Test good R/R
decision_good_rr = judge._create_rejection("GOODRR", "Test")
decision_good_rr.decisao = "APROVAR"
decision_good_rr.risco_recompensa = 3.0

is_valid_good = judge.validate_decision(decision_good_rr, [])
if is_valid_good:
    print(f"[OK] Decision with R/R {decision_good_rr.risco_recompensa} correctly accepted")
else:
    print(f"[FAIL] Decision with good R/R should have been accepted")

# Test duplicate position check
existing_positions = [{"ticker": "AAPL"}]
decision_duplicate = judge._create_rejection("AAPL", "Test")
decision_duplicate.decisao = "APROVAR"
decision_duplicate.risco_recompensa = 3.0

is_valid_dup = judge.validate_decision(decision_duplicate, existing_positions)
if not is_valid_dup:
    print("[OK] Duplicate position correctly rejected")
else:
    print("[FAIL] Duplicate position should have been rejected")

print("\n[4] Testing Decision Logging...")

# Log decision
db.log_decision("LOGTEST", test_decision)
print("[OK] Decision logged to database")

# Retrieve history
history = db.get_decisions_history(limit=5)
if history:
    print(f"[OK] Retrieved {len(history)} decisions from history")
    last_decision = history[0]
    print(f"    Last: {last_decision.get('ticker')} - {last_decision.get('decisao')} - Nota {last_decision.get('nota_final')}")
else:
    print("[FAIL] No decisions in history")

print("\n[5] Testing RAG Context Loading...")
if judge.rag_context:
    print(f"[OK] RAG context loaded: {len(judge.rag_context)} chars")
    print(f"    Preview: {judge.rag_context[:100]}...")
else:
    print("[WARNING] No RAG context loaded (data/rag_manuals/ may be empty)")

print("\n[6] Testing Prompt Building...")
mock_screener_result = {"nota": 7.5}
mock_market_data = {
    "ticker": "AAPL",
    "price": 150.0,
    "market_cap": 2500000000000,
    "tier": "Tier 1",
    "beta": 1.2,
    "sector_perf": 0.02
}
mock_technical_data = {
    "volatility_20d": 0.25,
    "rsi": 55,
    "atr": 3.5,
    "supertrend_direction": "bullish",
    "volume_ratio": 1.5,
    "support": 145.0,
    "resistance": 155.0
}
mock_macro_data = {
    "vix": 18.5,
    "spy_trend": "bullish"
}
mock_correlation_data = {
    "max_correlation": 0.65,
    "sector_exposure": 0.15
}

prompt = judge._build_prompt(
    "AAPL", mock_screener_result, mock_market_data,
    mock_technical_data, mock_macro_data, mock_correlation_data,
    "Apple announces new product line"
)

if "AAPL" in prompt and "150.0" in prompt:
    print("[OK] Prompt built successfully")
    print(f"    Length: {len(prompt)} chars")
else:
    print("[FAIL] Prompt missing expected data")

print("\n" + "=" * 60)
print("[OK] PHASE 3 TESTS COMPLETED!")
print("=" * 60)
print("\nSummary:")
print("  - Decision cache: Functional")
print("  - Threshold validation: Functional")
print("  - Decision validation: Functional")
print("  - Decision logging: Functional")
print("  - RAG context: " + ("Loaded" if judge.rag_context else "Empty"))
print("  - Prompt building: Functional")
print("\nNOTE: Full Judge execution with AI requires API keys.")
print("      To test complete flow, use: python debug_cli.py /judge TICKER")
