"""
DEBUG COMMANDS - Sistema de Inspeção de JSONs do Pipeline

Comandos disponíveis:
- /buzz                    -> Ver output do Buzz Factory (Phase 0)
- /news [TICKER]           -> Ver notícias raw do scraper
- /gnews [TICKER]          -> Ver notícias do GNews API
- /gnews-treated [TICKER]  -> Ver notícias após tratamento de IA (Gemini)
- /technical [TICKER]      -> Ver análise técnica completa
- /screener [TICKER]       -> Ver resultado do screener (Gemini)
- /risk [TICKER]           -> Ver análise de risco (Beta, Drawdown)
- /correlation             -> Ver matriz de correlação do portfolio
- /judge [TICKER]          -> Ver decisão completa do Judge (GPT)
- /grounding [TICKER]      -> Ver resultado do Google Grounding
- /execution [TICKER]      -> Ver cálculos de execução (stops, size, etc)
- /portfolio               -> Ver estado atual do portfolio
- /config                  -> Ver configurações carregadas
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DebugCommands:
    """
    Sistema de debug para inspecionar JSONs em cada etapa do pipeline.
    """

    def __init__(self, orchestrator):
        """
        Inicializa o sistema de debug.

        Args:
            orchestrator: Instância do Orchestrator com acesso a todos os componentes
        """
        self.orchestrator = orchestrator
        self.config = orchestrator.config
        self.output_dir = Path("data/debug_outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _save_json(self, data: Any, filename: str) -> str:
        """Salva JSON em arquivo e retorna path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"{filename}_{timestamp}.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        return str(filepath)

    def _print_json(self, data: Any, title: str = ""):
        """Pretty print JSON no console."""
        if title:
            print(f"\n{'='*80}")
            print(f"  {title}")
            print(f"{'='*80}\n")

        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        print(f"\n{'='*80}\n")

    async def cmd_buzz(self) -> Dict[str, Any]:
        """
        Comando: /buzz
        Mostra output do Buzz Factory (Phase 0).
        """
        print("\n🔍 Executando Buzz Factory (Phase 0)...\n")

        candidates = await self.orchestrator.buzz_factory.generate_daily_buzz()

        result = {
            "timestamp": datetime.now().isoformat(),
            "total_candidates": len(candidates),
            "candidates": [
                {
                    "ticker": c.ticker,
                    "source": c.source,
                    "buzz_score": c.buzz_score,
                    "reason": c.reason,
                    "detected_at": c.detected_at.isoformat()
                }
                for c in candidates
            ]
        }

        # Salvar e exibir
        filepath = self._save_json(result, "buzz_factory")
        self._print_json(result, "BUZZ FACTORY OUTPUT (Phase 0)")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_news(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /news [TICKER]
        Mostra notícias raw do scraper.
        """
        print(f"\n🔍 Buscando notícias RAW para {ticker}...\n")

        articles = await self.orchestrator.news_scraper.get_news(ticker)

        result = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "total_articles": len(articles),
            "articles": [
                {
                    "title": a.title,
                    "url": a.url,
                    "published_date": a.published_date.isoformat() if a.published_date else None,
                    "source": a.source,
                    "summary": a.summary[:200] + "..." if a.summary and len(a.summary) > 200 else a.summary
                }
                for a in articles
            ]
        }

        filepath = self._save_json(result, f"news_raw_{ticker}")
        self._print_json(result, f"RAW NEWS for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_gnews(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /gnews [TICKER]
        Mostra notícias do GNews API.
        """
        print(f"\n🔍 Buscando notícias no GNews para {ticker}...\n")

        # Importar news_aggregator se existir
        try:
            from src.collectors.news_aggregator import NewsAggregator
            aggregator = NewsAggregator(self.config)
            gnews_articles = await aggregator.get_gnews(ticker)

            result = {
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "source": "GNews API",
                "total_articles": len(gnews_articles),
                "articles": gnews_articles
            }

        except ImportError:
            result = {
                "error": "NewsAggregator not implemented yet",
                "ticker": ticker
            }

        filepath = self._save_json(result, f"gnews_{ticker}")
        self._print_json(result, f"GNEWS API for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_gnews_treated(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /gnews-treated [TICKER]
        Mostra notícias após tratamento de IA (Gemini NLP extraction).
        """
        print(f"\n🔍 Buscando notícias TRATADAS (Gemini NLP) para {ticker}...\n")

        try:
            from src.collectors.news_aggregator import NewsAggregator
            aggregator = NewsAggregator(self.config, ai_gateway=self.orchestrator.ai_gateway)

            # Buscar notícias raw
            gnews_articles = await aggregator.get_gnews(ticker)

            # Processar com Gemini (extração de tickers, sentiment, etc)
            treated = await aggregator.extract_tickers_and_sentiment(gnews_articles)

            result = {
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "source": "GNews + Gemini NLP",
                "total_articles": len(treated),
                "treated_articles": treated
            }

        except ImportError:
            result = {
                "error": "NewsAggregator not implemented yet",
                "ticker": ticker
            }

        filepath = self._save_json(result, f"gnews_treated_{ticker}")
        self._print_json(result, f"GNEWS TREATED (Gemini NLP) for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_technical(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /technical [TICKER]
        Mostra análise técnica completa.
        """
        print(f"\n🔍 Analisando dados técnicos para {ticker}...\n")

        technical_data = await self.orchestrator.technical.analyze(ticker)

        result = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "technical_analysis": technical_data
        }

        filepath = self._save_json(result, f"technical_{ticker}")
        self._print_json(result, f"TECHNICAL ANALYSIS for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_screener(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /screener [TICKER]
        Mostra resultado do screener (Gemini Phase 1).
        """
        print(f"\n🔍 Executando Screener (Gemini) para {ticker}...\n")

        # Coletar dados necessários
        market_data = await self.orchestrator.market_data.get_stock_data(ticker)
        technical_data = await self.orchestrator.technical.analyze(ticker)
        news_summary = await self.orchestrator.news_scraper.get_news_summary(ticker)

        # Executar screener
        screener_result = await self.orchestrator.screener.screen(
            market_data=market_data,
            technical_data=technical_data,
            news_summary=news_summary
        )

        result = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "screener_result": {
                "nota": screener_result.nota,
                "vies": screener_result.vies,
                "resumo": screener_result.resumo,
                "confianca": screener_result.confianca,
                "passed": screener_result.passed,
                "timestamp": screener_result.timestamp.isoformat()
            }
        }

        filepath = self._save_json(result, f"screener_{ticker}")
        self._print_json(result, f"SCREENER RESULT (Gemini Phase 1) for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_risk(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /risk [TICKER]
        Mostra análise de risco (Beta, Drawdown, etc).
        """
        print(f"\n🔍 Analisando risco para {ticker}...\n")

        market_data = await self.orchestrator.market_data.get_stock_data(ticker)
        technical_data = await self.orchestrator.technical.analyze(ticker)

        # Calcular métricas de risco
        beta = market_data.get("beta", 1.0) if isinstance(market_data, dict) else getattr(market_data, "beta", 1.0)
        volume_ratio = technical_data.get("volume_ratio", 1.0) if isinstance(technical_data, dict) else 1.0

        beta_adjustment = self.orchestrator.risk_calc.calculate_beta_adjustment(beta, volume_ratio)

        # Estado do portfolio
        defensive_mode = self.orchestrator.state_manager.is_defensive_mode()
        defensive_mult = self.orchestrator.state_manager.get_defensive_multiplier()
        current_dd = self.orchestrator.state_manager.get_current_drawdown()

        result = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "risk_analysis": {
                "beta": beta,
                "volume_ratio": volume_ratio,
                "beta_adjustment": beta_adjustment,
                "portfolio_state": {
                    "defensive_mode": defensive_mode,
                    "defensive_multiplier": defensive_mult,
                    "current_drawdown": current_dd
                }
            }
        }

        filepath = self._save_json(result, f"risk_{ticker}")
        self._print_json(result, f"RISK ANALYSIS (Phase 2) for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_correlation(self) -> Dict[str, Any]:
        """
        Comando: /correlation
        Mostra matriz de correlação do portfolio.
        """
        print(f"\n🔍 Calculando matriz de correlação...\n")

        # Get open positions
        positions = self.orchestrator.state_manager.get_open_positions()

        if not positions:
            print("⚠️  Nenhuma posição aberta no portfolio\n")
            return {"error": "No open positions"}

        # Calculate correlation matrix
        correlation_matrix = await self.orchestrator.correlation.calculate_portfolio_correlation()

        result = {
            "timestamp": datetime.now().isoformat(),
            "total_positions": len(positions),
            "tickers": [p.ticker for p in positions],
            "correlation_matrix": correlation_matrix
        }

        filepath = self._save_json(result, "correlation_matrix")
        self._print_json(result, "PORTFOLIO CORRELATION MATRIX (Phase 2)")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_judge(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /judge [TICKER]
        Mostra decisão completa do Judge (GPT Phase 3).
        """
        print(f"\n🔍 Consultando o Judge (GPT) para {ticker}...\n")

        # Coletar todos os dados necessários
        screener_result = await self.cmd_screener(ticker)
        market_data = await self.orchestrator.market_data.get_stock_data(ticker)
        technical_data = await self.orchestrator.technical.analyze(ticker)
        macro_data = await self.orchestrator.macro_data.get_macro_snapshot()

        # Executar Judge
        decision = await self.orchestrator.judge.judge(
            ticker=ticker,
            screener_result=screener_result,
            market_data=market_data,
            technical_data=technical_data,
            macro_data=macro_data,
            correlation_data={},
            news_details=""
        )

        result = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "judge_decision": {
                "decisao": decision.decisao,
                "nota_final": decision.nota_final,
                "entry_price": decision.entry_price,
                "stop_loss": decision.stop_loss,
                "take_profit_1": decision.take_profit_1,
                "take_profit_2": decision.take_profit_2,
                "direcao": decision.direcao,
                "tamanho_sugerido": decision.tamanho_sugerido,
                "justificativa": decision.justificativa,
                "alertas": decision.alertas
            }
        }

        filepath = self._save_json(result, f"judge_{ticker}")
        self._print_json(result, f"JUDGE DECISION (GPT Phase 3) for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_grounding(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /grounding [TICKER]
        Mostra resultado do Google Grounding.
        """
        print(f"\n🔍 Executando Google Grounding para {ticker}...\n")

        try:
            news_summary = await self.orchestrator.news_scraper.get_news_summary(ticker)

            grounding_result = await self.orchestrator.grounding.verify_news(
                ticker=ticker,
                news_title=news_summary
            )

            result = {
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "grounding_result": {
                    "verified": grounding_result.verified,
                    "confidence": grounding_result.confidence,
                    "sources": grounding_result.sources,
                    "summary": grounding_result.summary
                }
            }

        except Exception as e:
            result = {
                "error": str(e),
                "ticker": ticker
            }

        filepath = self._save_json(result, f"grounding_{ticker}")
        self._print_json(result, f"GOOGLE GROUNDING for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_execution(self, ticker: str) -> Dict[str, Any]:
        """
        Comando: /execution [TICKER]
        Mostra cálculos de execução (stops, position size, etc).
        """
        print(f"\n🔍 Calculando parâmetros de execução para {ticker}...\n")

        # Simular decisão de entrada
        decision_data = await self.cmd_judge(ticker)
        decision = decision_data.get("judge_decision", {})

        if decision.get("decisao") != "APROVAR":
            print("⚠️  Judge rejeitou este ticker\n")
            return {"error": "Ticker rejected by Judge", "ticker": ticker}

        # Calcular stops
        technical_data = await self.orchestrator.technical.analyze(ticker)
        atr = technical_data.get("atr", 1.0)

        stop_data = self.orchestrator.order_manager.calculate_stop_loss(
            ticker=ticker,
            entry_price=decision.get("entry_price", 100),
            atr=atr,
            direction=decision.get("direcao", "LONG"),
            has_nearby_earnings=False
        )

        # Calcular position size
        position_size = self.orchestrator.position_sizer.calculate(
            capital=self.orchestrator.state_manager.capital,
            entry_price=decision.get("entry_price", 100),
            stop_loss=stop_data["physical_stop"],
            ticker=ticker,
            tier="tier1_large_cap",
            size_suggestion=decision.get("tamanho_sugerido", "NORMAL")
        )

        result = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "execution_params": {
                "entry_price": decision.get("entry_price"),
                "direction": decision.get("direcao"),
                "stops": stop_data,
                "position_size": {
                    "shares": position_size.shares,
                    "total_value": position_size.total_value,
                    "risk_amount": position_size.risk_amount,
                    "reason": position_size.reason
                },
                "take_profits": {
                    "tp1": decision.get("take_profit_1"),
                    "tp2": decision.get("take_profit_2")
                }
            }
        }

        filepath = self._save_json(result, f"execution_{ticker}")
        self._print_json(result, f"EXECUTION PARAMETERS (Phase 4) for {ticker}")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def cmd_portfolio(self) -> Dict[str, Any]:
        """
        Comando: /portfolio
        Mostra estado atual do portfolio.
        """
        print(f"\n🔍 Estado do Portfolio...\n")

        positions = self.orchestrator.state_manager.get_open_positions()
        exposure_by_sector = self.orchestrator.state_manager.get_exposure_by_sector()

        result = {
            "timestamp": datetime.now().isoformat(),
            "capital": self.orchestrator.state_manager.capital,
            "current_drawdown": self.orchestrator.state_manager.get_current_drawdown(),
            "defensive_mode": self.orchestrator.state_manager.is_defensive_mode(),
            "kill_switch_active": self.orchestrator.state_manager.kill_switch_active,
            "total_positions": len(positions),
            "positions": [
                {
                    "ticker": p.ticker,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "quantity": p.quantity,
                    "unrealized_pnl": p.unrealized_pnl
                }
                for p in positions
            ],
            "exposure_by_sector": exposure_by_sector
        }

        filepath = self._save_json(result, "portfolio_state")
        self._print_json(result, "PORTFOLIO STATE")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    def cmd_config(self) -> Dict[str, Any]:
        """
        Comando: /config
        Mostra configurações carregadas.
        """
        print(f"\n🔍 Configurações do Sistema...\n")

        result = {
            "timestamp": datetime.now().isoformat(),
            "config": self.config
        }

        filepath = self._save_json(result, "system_config")
        self._print_json(result, "SYSTEM CONFIGURATION")

        print(f"💾 Salvo em: {filepath}\n")
        return result

    async def run_command(self, command: str) -> Optional[Dict[str, Any]]:
        """
        Executa um comando de debug.

        Args:
            command: String do comando (ex: "/buzz", "/news AAPL")

        Returns:
            Dict com resultado ou None se comando inválido
        """
        parts = command.strip().split()

        if not parts or not parts[0].startswith("/"):
            print("⚠️  Comando inválido. Use /help para ver comandos disponíveis.")
            return None

        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        try:
            if cmd == "/help":
                print(__doc__)
                return None

            elif cmd == "/buzz":
                return await self.cmd_buzz()

            elif cmd == "/news":
                if not args:
                    print("⚠️  Uso: /news [TICKER]")
                    return None
                return await self.cmd_news(args[0].upper())

            elif cmd == "/gnews":
                if not args:
                    print("⚠️  Uso: /gnews [TICKER]")
                    return None
                return await self.cmd_gnews(args[0].upper())

            elif cmd == "/gnews-treated":
                if not args:
                    print("⚠️  Uso: /gnews-treated [TICKER]")
                    return None
                return await self.cmd_gnews_treated(args[0].upper())

            elif cmd == "/technical":
                if not args:
                    print("⚠️  Uso: /technical [TICKER]")
                    return None
                return await self.cmd_technical(args[0].upper())

            elif cmd == "/screener":
                if not args:
                    print("⚠️  Uso: /screener [TICKER]")
                    return None
                return await self.cmd_screener(args[0].upper())

            elif cmd == "/risk":
                if not args:
                    print("⚠️  Uso: /risk [TICKER]")
                    return None
                return await self.cmd_risk(args[0].upper())

            elif cmd == "/correlation":
                return await self.cmd_correlation()

            elif cmd == "/judge":
                if not args:
                    print("⚠️  Uso: /judge [TICKER]")
                    return None
                return await self.cmd_judge(args[0].upper())

            elif cmd == "/grounding":
                if not args:
                    print("⚠️  Uso: /grounding [TICKER]")
                    return None
                return await self.cmd_grounding(args[0].upper())

            elif cmd == "/execution":
                if not args:
                    print("⚠️  Uso: /execution [TICKER]")
                    return None
                return await self.cmd_execution(args[0].upper())

            elif cmd == "/portfolio":
                return await self.cmd_portfolio()

            elif cmd == "/config":
                return self.cmd_config()

            else:
                print(f"⚠️  Comando desconhecido: {cmd}")
                print("Use /help para ver comandos disponíveis.")
                return None

        except Exception as e:
            logger.error(f"Error executing command {cmd}: {e}")
            print(f"\n❌ Erro ao executar comando: {e}\n")
            return None
