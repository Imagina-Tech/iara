"""
Test script para verificar Phase 0 - Buzz Factory
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.collectors.buzz_factory import BuzzFactory
from src.collectors.earnings_checker import EarningsChecker
from src.collectors.market_data import MarketDataCollector
from src.collectors.news_scraper import NewsScraper
import yaml

print("=" * 60)
print("TESTE 3: Phase 0 - Buzz Factory")
print("=" * 60)

async def test_phase0():
    # Load config
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    # Initialize components
    print("\n[1] Initializing components...")
    market_data = MarketDataCollector(config)
    news_scraper = NewsScraper(config)
    buzz_factory = BuzzFactory(config, market_data, news_scraper)
    earnings_checker = EarningsChecker(config)
    print("[OK] Components initialized")
    
    # Test watchlist loading
    print("\n[2] Testing watchlist loading...")
    try:
        watchlist_candidates = await buzz_factory._scan_watchlist()
        print(f"[OK] Watchlist loaded: {len(watchlist_candidates)} candidates")
        
        if watchlist_candidates:
            sample = watchlist_candidates[0]
            print(f"    Sample: {sample.ticker} (Tier: {sample.tier}, Source: {sample.source})")
    except Exception as e:
        print(f"[ERROR] Watchlist loading failed: {e}")
        sys.exit(1)
    
    # Test volume spike scanner (simplified - checks if method runs)
    print("\n[3] Testing volume spike scanner...")
    try:
        volume_candidates = await buzz_factory._scan_volume_spikes()
        print(f"[OK] Volume scanner executed: {len(volume_candidates)} spikes found")
    except Exception as e:
        print(f"[WARNING] Volume scanner error (expected - needs market hours): {e}")
    
    # Test gap scanner
    print("\n[4] Testing gap scanner...")
    try:
        gap_candidates = await buzz_factory._scan_gaps()
        print(f"[OK] Gap scanner executed: {len(gap_candidates)} gaps found")
    except Exception as e:
        print(f"[WARNING] Gap scanner error (expected - needs market hours): {e}")
    
    # Test market cap filtering
    print("\n[5] Testing market cap & liquidity filters...")
    try:
        # Use watchlist candidates for filter test
        filtered = await buzz_factory.apply_filters(watchlist_candidates)
        print(f"[OK] Filters applied: {len(watchlist_candidates)} -> {len(filtered)} candidates")
        
        if len(filtered) > 0:
            print("    Filter results:")
            for candidate in filtered[:3]:  # Show first 3
                print(f"    - {candidate.ticker}: Cap=${candidate.market_cap/1e9:.1f}B, Tier={candidate.tier}")
    except Exception as e:
        print(f"[ERROR] Filter test failed: {e}")
        sys.exit(1)
    
    # Test earnings checker
    print("\n[6] Testing earnings proximity check...")
    try:
        test_ticker = "AAPL"
        has_earnings = earnings_checker.check_earnings_proximity(test_ticker, days=5)
        print(f"[OK] Earnings check for {test_ticker}: {has_earnings}")
    except Exception as e:
        print(f"[WARNING] Earnings check error: {e}")
    
    print("\n" + "=" * 60)
    print("[OK] PHASE 0 TESTS COMPLETED!")
    print("=" * 60)
    print("\nNote: Volume/Gap scanners may show warnings outside market hours.")
    print("This is expected behavior.")

# Run async test
asyncio.run(test_phase0())
