"""
DATABASE - SQLite Schema e Helper Functions
Gerencia cache de decisões e logging de histórico
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)


class Database:
    """
    Gerenciador de banco de dados SQLite para IARA.

    Schemas:
    - decision_cache: Cache de decisões recentes (< 2h)
    - decision_log: Histórico completo de decisões
    - trade_history: Histórico de trades executados
    """

    def __init__(self, db_path: Union[str, Path] = "data/iara.db"):
        """
        Inicializa o banco de dados.

        Args:
            db_path: Caminho para o arquivo do banco de dados
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self) -> None:
        """Cria as tabelas se não existirem."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Tabela: decision_cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decision_cache (
                    ticker TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    nota_final REAL NOT NULL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit_1 REAL,
                    take_profit_2 REAL,
                    justificativa TEXT,
                    timestamp INTEGER NOT NULL,
                    PRIMARY KEY (ticker, timestamp)
                )
            """)

            # Tabela: decision_log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decision_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    nota_final REAL NOT NULL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit_1 REAL,
                    take_profit_2 REAL,
                    justificativa TEXT,
                    alertas TEXT,
                    timestamp INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tabela: trade_history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time INTEGER NOT NULL,
                    exit_price REAL,
                    exit_time INTEGER,
                    quantity INTEGER NOT NULL,
                    pnl REAL,
                    pnl_percent REAL,
                    reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Índices para performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_cache_ticker
                ON decision_cache(ticker)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_cache_timestamp
                ON decision_cache(timestamp DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_log_ticker
                ON decision_log(ticker)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_log_timestamp
                ON decision_log(timestamp DESC)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_history_ticker
                ON trade_history(ticker)
            """)

            conn.commit()
            logger.info("Database schema initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Retorna uma conexão com o banco de dados."""
        return sqlite3.connect(str(self.db_path))

    # === DECISION CACHE ===

    def get_cached_decision(self, ticker: str, max_age_hours: int = 2) -> Optional[Dict[str, Any]]:
        """
        Busca decisão em cache (< max_age_hours).

        Args:
            ticker: Ticker do ativo
            max_age_hours: Idade máxima do cache em horas

        Returns:
            Dict com decisão ou None se não encontrado
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            from datetime import timedelta
            cutoff_time = int((datetime.now() - timedelta(hours=max_age_hours)).timestamp())

            cursor.execute("""
                SELECT decision, nota_final, entry_price, stop_loss,
                       take_profit_1, take_profit_2, justificativa, timestamp
                FROM decision_cache
                WHERE ticker = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (ticker, cutoff_time))

            row = cursor.fetchone()

            if row:
                return {
                    "ticker": ticker,  # Add ticker to returned dict
                    "decisao": row[0],
                    "nota_final": row[1],
                    "entry_price": row[2],
                    "stop_loss": row[3],
                    "take_profit_1": row[4],
                    "take_profit_2": row[5],
                    "justificativa": row[6],
                    "timestamp": datetime.fromtimestamp(row[7]).isoformat(),
                    "cached": True
                }

            return None

        except Exception as e:
            logger.error(f"Error getting cached decision for {ticker}: {e}")
            return None
        finally:
            conn.close()

    def cache_decision(self, ticker: str, decision: Dict[str, Any]) -> bool:
        """
        Salva decisão em cache.

        Args:
            ticker: Ticker do ativo
            decision: Dict com dados da decisão

        Returns:
            True se salvou com sucesso
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO decision_cache
                (ticker, decision, nota_final, entry_price, stop_loss,
                 take_profit_1, take_profit_2, justificativa, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                decision.get("decisao", ""),
                decision.get("nota_final", 0),
                decision.get("entry_price"),
                decision.get("stop_loss"),
                decision.get("take_profit_1"),
                decision.get("take_profit_2"),
                decision.get("justificativa", ""),
                int(datetime.now().timestamp())
            ))

            conn.commit()
            logger.debug(f"Decision cached for {ticker}")
            return True

        except Exception as e:
            logger.error(f"Error caching decision for {ticker}: {e}")
            return False
        finally:
            conn.close()

    def clear_old_cache(self, max_age_hours: int = 24) -> int:
        """
        Remove entradas antigas do cache.

        Args:
            max_age_hours: Idade máxima em horas

        Returns:
            Número de registros removidos
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            from datetime import timedelta
            cutoff_time = int((datetime.now() - timedelta(hours=max_age_hours)).timestamp())

            cursor.execute("""
                DELETE FROM decision_cache
                WHERE timestamp < ?
            """, (cutoff_time,))

            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Cleared {deleted} old cache entries")

            return deleted

        except Exception as e:
            logger.error(f"Error clearing old cache: {e}")
            return 0
        finally:
            conn.close()

    # === DECISION LOG ===

    def log_decision(self, ticker: str, decision: Dict[str, Any]) -> int:
        """
        Registra decisão no histórico.

        Args:
            ticker: Ticker do ativo
            decision: Dict com dados da decisão

        Returns:
            ID do registro inserido ou 0 em caso de erro
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            alertas = ",".join(decision.get("alertas", []))

            cursor.execute("""
                INSERT INTO decision_log
                (ticker, decision, nota_final, entry_price, stop_loss,
                 take_profit_1, take_profit_2, justificativa, alertas, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                decision.get("decisao", ""),
                decision.get("nota_final", 0),
                decision.get("entry_price"),
                decision.get("stop_loss"),
                decision.get("take_profit_1"),
                decision.get("take_profit_2"),
                decision.get("justificativa", ""),
                alertas,
                int(datetime.now().timestamp())
            ))

            conn.commit()
            decision_id = cursor.lastrowid
            logger.info(f"Decision logged for {ticker} (ID: {decision_id})")
            return decision_id if decision_id is not None else 0

        except Exception as e:
            logger.error(f"Error logging decision for {ticker}: {e}")
            return 0
        finally:
            conn.close()

    def get_decisions_history(self, ticker: Optional[str] = None,
                               limit: int = 100) -> List[Dict[str, Any]]:
        """
        Busca histórico de decisões.

        Args:
            ticker: Filtrar por ticker (opcional)
            limit: Número máximo de registros

        Returns:
            Lista de decisões
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if ticker:
                cursor.execute("""
                    SELECT id, ticker, decision, nota_final, entry_price,
                           stop_loss, justificativa, timestamp
                    FROM decision_log
                    WHERE ticker = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (ticker, limit))
            else:
                cursor.execute("""
                    SELECT id, ticker, decision, nota_final, entry_price,
                           stop_loss, justificativa, timestamp
                    FROM decision_log
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "ticker": row[1],
                    "decisao": row[2],
                    "nota_final": row[3],
                    "entry_price": row[4],
                    "stop_loss": row[5],
                    "justificativa": row[6],
                    "timestamp": row[7]
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Error getting decisions history: {e}")
            return []
        finally:
            conn.close()

    # === TRADE HISTORY ===

    def log_trade_entry(self, ticker: str, direction: str, entry_price: float,
                         quantity: int) -> int:
        """
        Registra entrada em trade.

        Args:
            ticker: Ticker do ativo
            direction: LONG ou SHORT
            entry_price: Preço de entrada
            quantity: Quantidade de shares

        Returns:
            ID do registro inserido
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO trade_history
                (ticker, direction, entry_price, entry_time, quantity)
                VALUES (?, ?, ?, ?, ?)
            """, (
                ticker,
                direction,
                entry_price,
                int(datetime.now().timestamp()),
                quantity
            ))

            conn.commit()
            trade_id = cursor.lastrowid
            logger.info(f"Trade entry logged for {ticker} (ID: {trade_id})")
            return trade_id if trade_id is not None else 0

        except Exception as e:
            logger.error(f"Error logging trade entry for {ticker}: {e}")
            return 0
        finally:
            conn.close()

    def log_trade_exit(self, trade_id: int, exit_price: float,
                        reason: str = "") -> bool:
        """
        Registra saída de trade.

        Args:
            trade_id: ID do trade
            exit_price: Preço de saída
            reason: Motivo da saída

        Returns:
            True se atualizou com sucesso
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Buscar dados do trade
            cursor.execute("""
                SELECT entry_price, quantity, direction
                FROM trade_history
                WHERE id = ?
            """, (trade_id,))

            row = cursor.fetchone()
            if not row:
                logger.error(f"Trade {trade_id} not found")
                return False

            entry_price, quantity, direction = row

            # Calcular PnL
            if direction == "LONG":
                pnl = (exit_price - entry_price) * quantity
                pnl_percent = ((exit_price - entry_price) / entry_price) * 100
            else:  # SHORT
                pnl = (entry_price - exit_price) * quantity
                pnl_percent = ((entry_price - exit_price) / entry_price) * 100

            # Atualizar registro
            cursor.execute("""
                UPDATE trade_history
                SET exit_price = ?,
                    exit_time = ?,
                    pnl = ?,
                    pnl_percent = ?,
                    reason = ?
                WHERE id = ?
            """, (
                exit_price,
                int(datetime.now().timestamp()),
                pnl,
                pnl_percent,
                reason,
                trade_id
            ))

            conn.commit()
            logger.info(f"Trade exit logged for ID {trade_id}: PnL ${pnl:.2f} ({pnl_percent:.2f}%)")
            return True

        except Exception as e:
            logger.error(f"Error logging trade exit for ID {trade_id}: {e}")
            return False
        finally:
            conn.close()

    def get_trade_history(self, ticker: Optional[str] = None,
                           limit: int = 100) -> List[Dict[str, Any]]:
        """
        Busca histórico de trades.

        Args:
            ticker: Filtrar por ticker (opcional)
            limit: Número máximo de registros

        Returns:
            Lista de trades
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if ticker:
                cursor.execute("""
                    SELECT id, ticker, direction, entry_price, entry_time,
                           exit_price, exit_time, quantity, pnl, pnl_percent, reason
                    FROM trade_history
                    WHERE ticker = ?
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (ticker, limit))
            else:
                cursor.execute("""
                    SELECT id, ticker, direction, entry_price, entry_time,
                           exit_price, exit_time, quantity, pnl, pnl_percent, reason
                    FROM trade_history
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "ticker": row[1],
                    "direction": row[2],
                    "entry_price": row[3],
                    "entry_time": row[4],
                    "exit_price": row[5],
                    "exit_time": row[6],
                    "quantity": row[7],
                    "pnl": row[8],
                    "pnl_percent": row[9],
                    "reason": row[10]
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Error getting trade history: {e}")
            return []
        finally:
            conn.close()
