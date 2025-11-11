import os
import sqlite3
from typing import List, Dict, Optional


class DbTools:
    """Simple sqlite-based mock DB layer for checkcorporate server.

    By default this class DOES NOT open a real database connection. The
    methods `get_bilancio` and `get_piano_dei_conti` will return simulated
    responses unless `use_db=True` is passed to the constructor. This makes it
    safe to instantiate in environments where no DB access is available.

    Additionally, the class accepts optional `client_id` and `client_secret`
    parameters which are intended to be provided by the deployment (for
    example via Docker secrets / environment variables). These credentials are
    stored and can be used by the tool implementations to authenticate calls
    or to tag/annotate simulated SQL executions for auditing.
    """

    def __init__(
        self,
        db_path: str = "/data/bilancio.db",
        use_db: bool = False,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_endpoint: str | None = None,
    ) -> None:
        self.db_path = db_path
        self.use_db = bool(use_db)
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_endpoint = api_endpoint
        self.conn = None

        # If use_db is requested, open sqlite and ensure schema
        if self.use_db:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        # If we're not using a real DB, nothing to ensure
        if not self.use_db or self.conn is None:
            return

        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bilanci (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                societa TEXT NOT NULL,
                esercizio INTEGER NOT NULL,
                type TEXT NOT NULL,
                account TEXT NOT NULL,
                amount REAL NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS piano_conti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                societa TEXT NOT NULL,
                account TEXT NOT NULL,
                description TEXT,
                level INTEGER DEFAULT 1
            )
            """
        )

        # Populate with minimal mock data if empty
        cur.execute("SELECT COUNT(*) AS c FROM bilanci")
        if cur.fetchone()[0] == 0:
            # Insert mock bilanci rows
            sample = [
                ("ACME", 2024, "Economico", "4000", 12000.0),
                ("ACME", 2024, "Economico", "4010", 8000.0),
                ("ACME", 2024, "Patrimoniale", "1000", 50000.0),
                ("ACME", 2024, "Patrimoniale", "2000", 20000.0),
            ]
            cur.executemany(
                "INSERT INTO bilanci (societa, esercizio, type, account, amount) VALUES (?,?,?,?,?)",
                sample,
            )

        cur.execute("SELECT COUNT(*) AS c FROM piano_conti")
        if cur.fetchone()[0] == 0:
            sample_pc = [
                ("ACME", "1000", "Cassa", 1),
                ("ACME", "2000", "Banche", 1),
                ("ACME", "4000", "Ricavi vendite", 2),
                ("ACME", "4010", "Sconti attivi", 2),
            ]
            cur.executemany(
                "INSERT INTO piano_conti (societa, account, description, level) VALUES (?,?,?,?)",
                sample_pc,
            )

        self.conn.commit()

    def get_bilancio(self, societa: str, esercizio: int, tipo: str, limit: Optional[int] = 100) -> List[Dict]:
        """Mock query per recuperare dati di bilancio.

        Esegue una query aggregata sui conti per societa/esercizio/tipo.
        """
        # If not using real DB, return a simulated response
        tipo_db = tipo.lower()
        if tipo_db not in ("economico", "patrimoniale"):
            raise ValueError("tipo must be 'Economico' or 'Patrimoniale'")

        if not self.use_db or self.conn is None:
            # Simulated aggregated results. We include a masked client id in the
            # response to demonstrate that credentials were used by the tool.
            masked = None
            if self.client_id:
                masked = self.client_id[:4] + "*" * max(0, len(self.client_id) - 4)

            if tipo_db == "economico":
                base = [
                    {"account": "4000", "total": 12000.0},
                    {"account": "4010", "total": 8000.0},
                ][:limit]
            else:
                base = [
                    {"account": "1000", "total": 50000.0},
                    {"account": "2000", "total": 20000.0},
                ][:limit]

            # If credentials are present, add client_id_masked to each row to
            # show the values were available to the tool (simulated usage).
            if masked:
                for r in base:
                    r["client_id_masked"] = masked

            # If an API endpoint is configured, add it to the simulated result
            # so callers can verify which endpoint would be used.
            if self.api_endpoint:
                for r in base:
                    r["api_endpoint"] = self.api_endpoint

            return base

        # Fallback to real DB behavior if enabled
        cur = self.conn.cursor()
        sql = (
            "SELECT account, SUM(amount) AS total "
            "FROM bilanci "
            "WHERE societa = ? AND esercizio = ? AND LOWER(type) = ? "
            "GROUP BY account "
            "ORDER BY account LIMIT ?"
        )
        cur.execute(sql, (societa, esercizio, tipo_db, limit))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_piano_dei_conti(self, societa: str) -> List[Dict]:
        """Mock query per restituire il piano dei conti di una societa."""
        # If not using a real DB, return simulated chart of accounts
        if not self.use_db or self.conn is None:
            base = [
                {"account": "1000", "description": "Cassa", "level": 1},
                {"account": "2000", "description": "Banche", "level": 1},
                {"account": "4000", "description": "Ricavi vendite", "level": 2},
                {"account": "4010", "description": "Sconti attivi", "level": 2},
            ]

            # Attach masked client id if available
            if self.client_id:
                masked = self.client_id[:4] + "*" * max(0, len(self.client_id) - 4)
                for r in base:
                    r["client_id_masked"] = masked

            # Include api_endpoint in the simulated chart-of-accounts output
            if self.api_endpoint:
                for r in base:
                    r["api_endpoint"] = self.api_endpoint

            return base

        cur = self.conn.cursor()
        sql = "SELECT account, description, level FROM piano_conti WHERE societa = ? ORDER BY account"
        cur.execute(sql, (societa,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
