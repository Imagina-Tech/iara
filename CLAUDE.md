# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IARA (Institutional Automated Risk Analysis / Intelligent Automated Risk-Aware Trader) is an autonomous quantitative trading system focused on swing trading (3-5 days) with extreme capital protection. The system uses a hybrid architecture combining pure mathematics (Python local) for data and risk analysis with AI (cloud) for strategy and screening.

**Key Philosophy**: IARA is not just a trading bot—it's a complete treasury system. Unlike common bots that focus only on "Entry Signals," IARA was architected with **Survival** as the primary goal, implementing safeguards against flash crashes, cross-portfolio correlation, M&A detection (Poison Pill), and tiered execution for small caps.

## Common Commands

### Environment Setup
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Environment configuration
cp config/secrets.example.yaml config/secrets.yaml
# Edit .env with your API keys (OPENAI_API_KEY, GEMINI_API_KEY, etc.)
```

### Running the System
```bash
# Start IARA main system
python main.py

# The system initializes with:
# - Paper trading by default (line 115 in main.py)
# - Starting capital: $100,000 (line 96 in main.py)
# - Telegram disabled by default (line 154 in main.py)
```

### Testing
```bash
# Run all tests
pytest

# Run specific test files
pytest tests/test_risk.py
pytest tests/test_correlation.py

# Run with async support
pytest -v --asyncio-mode=auto
```

## Architecture: The 6-Phase Pipeline

IARA operates in a sequential flow through 6 phases combining math and AI:

### Phase 0: Buzz Factory (08:00 - Pre-Market)
**Location**: `src/collectors/buzz_factory.py`

Generates the daily opportunity list by combining:
- Watchlist (fixed assets from `config/watchlist.json`)
- Volume scans (>2x average via `yfinance`)
- Gap scans (>3%)
- News scraping (catalysts via `newspaper3k`)

**Dynamic Tiering**: Classifies assets into Tier 1 (Blue Chips >$4B) and Tier 2 (Small Caps >$800M).

### Phase 1: Screener (10:30 - Hybrid Triage)
**Location**: `src/decision/screener.py`
**AI Model**: Google Gemini 3 Flash (Free Tier)

Low-cost AI triage that scores candidates 0-10 based on:
- Volume (0-2 pts)
- Trend (0-2 pts)
- Momentum (0-2 pts)
- Catalyst (0-2 pts)
- Risk/Return (0-2 pts)

**Threshold**: Score ≥7 passes to Phase 2.
**Prompt**: `config/prompts/screener.md`
**Rate Limiting**: 4-second sleep between calls (free tier constraint).

### Phase 2: The Vault (Mathematics Only)
**Location**: `src/analysis/`

No AI makes decisions without passing through the math layer:
- **Correlation** (`correlation.py`): Blocks entry if correlation with current portfolio >0.75
- **Beta Intelligence** (`risk_math.py`): Allows Beta >3.0 only with high volume, adjusting lot size
- **Drawdown Guard** (`risk_math.py`): Reduces lot 50% if DD >5%, activates Kill Switch at DD >8%
- **Technical Analysis** (`technical.py`): RSI, ATR, SuperTrend using `pandas_ta`

### Phase 3: The Judge (AI Decision Hierarchy)
**Location**: `src/decision/judge.py`
**AI Model**: GPT-4/5 (OpenAI) with RAG access
**Fallback Chain**: OpenAI → GPT-4o-mini → Claude 3.5 → Gemini

Strategic decision based on complete dossiers:
- Screener score + market data
- Technical analysis from Phase 2
- Macro context (VIX, SPY)
- Portfolio correlation
- Detailed news
- RAG context (strategy manuals)

**Output**: JSON with entry/stop/take-profit levels, position size suggestion.
**Threshold**: Score ≥8 to APPROVE.
**Prompt**: `config/prompts/judge.md`

### Phase 4: Armored Execution
**Location**: `src/execution/`

Order protocol to avoid slippage and errors:
- **Entry**: STOP-LIMIT only (+0.5% from trigger), never market orders
- **Position Sizing** (`position_sizer.py`): Fixed 1-2% risk adjusted by ATR and Tier (reducer for Small Caps)
- **Protection** (`order_manager.py`): Physical stop loss sent to broker + backup stop at -10%
- **Broker API** (`broker_api.py`): Supports paper trading and `ccxt` integration

### Phase 5: The Guardian (24/7 Monitoring)
**Location**: `src/monitoring/`

Continuous monitoring and emergency protocols:
- **Watchdog** (`watchdog.py`): 1-min loop monitoring price vs stop/TP, flash crash detection (>5% in 1 min)
- **Sentinel** (`sentinel.py`): 5-min loop for news on open positions with AI impact analysis
- **Poison Pill** (`poison_pill.py`): Overnight scanner for M&A/SEC investigations. If found, cancels stops and seeks +60% target
- **Telegram Bot** (`telegram_bot.py`): Remote Kill Switch via `/kill` command

### Phase 6: State Management
**Location**: `src/core/state_manager.py`

Central system memory controlling:
- Capital and positions
- Drawdown tracking (daily: 2%, total: 6%)
- Kill Switch activation
- Position limits (max 5 simultaneous)
- Exposure by sector

## Risk Management Rules

### Global Limits (config/settings.yaml)
- **Daily Drawdown**: 2% max
- **Total Drawdown**: 6% max (triggers Kill Switch)
- **Risk per Trade**: 1% base
- **Max Positions**: 5 simultaneous
- **Max Correlation**: 0.7 between assets
- **Max Exposure**: 80% of capital

### Kill Switch
**Auto-activation triggers**:
1. Total drawdown ≥6%
2. Flash crash ≥10%
3. Manual `/kill` command via Telegram

**Actions**:
- Closes all positions immediately
- Suspends new operations
- Sends critical alert

## AI Gateway Hierarchy

**Location**: `src/decision/ai_gateway.py`

The `AIGateway` class manages fallback across AI providers:

1. **Screener (Phase 1)**: Gemini Free (zero cost)
2. **Judge (Phase 3)**: GPT-4/5 (high quality) → Fallback: Claude 3.5
3. **Sentinel (Phase 5)**: GPT-4 Turbo (fast)
4. **Grounding**: Google Search API (free)

The gateway automatically retries with the next provider if one fails.

## Core Components

### Orchestrator (`src/core/orchestrator.py`)
The maestro that coordinates all 6 phases. Controls:
- Phase sequencing and timing
- Market hours checking (`is_market_open()`)
- Cycle management

**Note**: Many phase methods are currently stubs (marked with `# TODO`), waiting for full implementation.

### Data Collectors (`src/collectors/`)
- **market_data.py**: Real-time and historical data via `yfinance`
- **news_scraper.py**: News scraping with `newspaper3k`
- **macro_data.py**: VIX, SPY, sector performance
- **buzz_factory.py**: Combines all sources for Phase 0

### Main Entry Point (`main.py`)
Initializes all components and starts parallel tasks:
```python
tasks = [
    orchestrator.start(),
    watchdog.start(),
    sentinel.start(),
    # telegram.start() - commented out by default
]
```

Proper cleanup on shutdown including broker disconnection.

## Configuration

### settings.yaml
Primary configuration including:
- Risk parameters
- Market hours (Eastern time)
- Tier definitions (Large/Mid/Small cap thresholds)
- Liquidity filters
- Technical indicator periods
- AI thresholds

### .env
Sensitive credentials (never commit):
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- Broker API credentials

### watchlist.json
Fixed list of Tier 1 assets for Phase 0.

## Important Implementation Notes

### Async Architecture
The system is fully async (`asyncio`). All I/O operations (API calls, data fetching) should use `async/await`.

### Logging
Uses Python's `logging` module with structured format:
```python
logger = logging.getLogger(__name__)
```
Logs to both console and daily files in `data/logs/`.

### Paper Trading Default
The system defaults to paper trading mode. To switch to live trading:
```python
broker = BrokerAPI.create(config, broker_type="ccxt")  # Change from "paper"
```

### Position Sizing Formula
```python
# Base formula in position_sizer.py:
risk_amount = capital * base_risk_pct * tier_multiplier * suggestion_multiplier
shares = risk_amount / (entry_price - stop_loss)
```

### Correlation Veto
**Critical Rule**: If `correlation > 0.7` with any open position, the trade is automatically rejected (Phase 2). This is non-negotiable.

### Rate Limiting
Gemini Free Tier requires 4-second delays between calls. This is handled in the screener but be aware when making changes.

## Data Storage

- **SQLite**: Used for logs and caching (no schema files in repo yet)
- **JSON**: Local cache and configuration files
- **No external database**: Fully self-contained

## Development Workflow

When implementing new features:
1. Check the phase it belongs to (0-5)
2. Update the corresponding module in `src/`
3. Add proper async support if doing I/O
4. Update `orchestrator.py` if adding a new phase step
5. Add tests in `tests/`
6. Update configuration in `config/settings.yaml` if needed
7. Consider impact on `state_manager.py` for risk limits

## Critical Safety Mechanisms

1. **Never bypass correlation check**: Phase 2 veto is final
2. **Always send physical stops**: Phase 4 requirement
3. **Respect Kill Switch**: Once activated, requires manual reset
4. **Validate position sizing**: Never exceed 20% capital in single position
5. **Check market hours**: No operations outside market hours (except overnight scans)

## Known TODOs

The codebase has several `# TODO:` markers for incomplete features:
- Full Phase 0-5 implementation in orchestrator
- RAG integration for Judge's strategy manuals
- Complete broker API integration (currently paper trading only)
- Sector exposure tracking in state manager
- Database schema and persistence
- Web dashboard (optional, mentioned in blueprint)

## Tech Stack Summary

- **Core**: Python 3.10+
- **Data**: `yfinance`, `pandas`, `numpy`
- **Technical Analysis**: `pandas-ta`
- **AI APIs**: `openai`, `google-generativeai`, `anthropic`
- **News**: `newspaper3k`, `beautifulsoup4`
- **Broker**: `ccxt` (when enabled)
- **Messaging**: `python-telegram-bot`
- **Storage**: `sqlite3`
- **Async**: `asyncio`, `aiohttp`

## Version

Current version: v25.0 "Atomic Survivor"
