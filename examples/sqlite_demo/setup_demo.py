"""Create a synthetic SQLite database (`demo.sqlite`) for the Irides local quickstart."""

import sqlite3
from pathlib import Path


def create_demo_db(db_path: Path | None = None) -> Path:
    target = db_path or (Path(__file__).resolve().parent / "demo.sqlite")
    if target.exists():
        target.unlink()

    conn = sqlite3.connect(str(target))
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                order_number TEXT NOT NULL UNIQUE,
                total_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'EUR',
                placed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE INDEX idx_orders_customer_placed ON orders(customer_id, placed_at);
            """
        )
        conn.commit()
    finally:
        conn.close()
    return target


if __name__ == "__main__":
    path = create_demo_db()
    print(f"Created demo SQLite database at {path}")
