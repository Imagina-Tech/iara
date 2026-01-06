"""
Test script para verificar Database initialization
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.database import Database

print("=" * 60)
print("TESTE 2: Database Initialization")
print("=" * 60)

# Create test database
test_db_path = Path(__file__).parent / "data" / "test_iara.db"
test_db_path.parent.mkdir(exist_ok=True)

print(f"\n[1] Creating database at: {test_db_path}")
db = Database(str(test_db_path))
print("[OK] Database created")

# Test caching decision
print("\n[2] Testing decision cache...")
test_decision = {
    "ticker": "AAPL",
    "decisao": "APROVAR",
    "nota_final": 8.5,
    "entry_price": 150.0,
    "stop_loss": 145.0,
    "take_profit_1": 155.0,
    "take_profit_2": 160.0,
    "justificativa": "Test decision",
    "timestamp": datetime.now().isoformat()
}

db.cache_decision("AAPL", test_decision)
print("[OK] Decision cached")

# Retrieve from cache
cached = db.get_cached_decision("AAPL", max_age_hours=2)
if cached and cached.get("ticker") == "AAPL":
    print("[OK] Cache retrieval successful")
    print(f"    Cached ticker: {cached.get('ticker')}")
    print(f"    Nota: {cached.get('nota_final')}")
else:
    print("[ERROR] Cache retrieval failed")
    sys.exit(1)

# Test decision logging
print("\n[3] Testing decision logging...")
db.log_decision("AAPL", test_decision)
print("[OK] Decision logged")

# Test trade logging
print("\n[4] Testing trade logging...")
trade_id = db.log_trade_entry("AAPL", "LONG", 150.0, 100)
print(f"[OK] Trade entry logged (ID: {trade_id})")

# Update trade exit
db.log_trade_exit(trade_id, 155.0, "Take profit hit")
print("[OK] Trade exit logged")

print("\n" + "=" * 60)
print("[OK] TODOS OS TESTES DE DATABASE PASSARAM!")
print("=" * 60)

# Cleanup
import os
if test_db_path.exists():
    os.remove(test_db_path)
    print("\n[Cleanup] Test database removed")
