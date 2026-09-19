"""Controller for initializing configuration templates."""

import os
from pathlib import Path
from typing import Any, Dict


SAMPLE_YAML = """# irides.yaml - Irides database configuration file
# Learn more: https://github.com/GianAndreaSechi/irides

targets:
  # SQLite example (no server needed)
  # local_sqlite:
  #   type: sqlite
  #   database: ./data.db

  # PostgreSQL example
  # my_postgres:
  #   type: postgres
  #   host: localhost
  #   port: 5432
  #   user: postgres
  #   password: "${PG_PASSWORD:-postgres}"
  #   database: my_database

  # MySQL example
  # my_mysql:
  #   type: mysql
  #   host: localhost
  #   port: 3306
  #   user: root
  #   password: "${MYSQL_PASSWORD}"

  # MongoDB example
  # my_mongo:
  #   type: mongodb
  #   host: localhost
  #   port: 27017
  #   username: admin
  #   password: "${MONGO_PASSWORD}"
  #   authSource: admin
"""

SAMPLE_ENV = """# .env - Irides environment configuration
# Learn more: https://github.com/GianAndreaSechi/irides

DB_TARGETS=sample_pg

# PostgreSQL sample target
DB_TARGET_SAMPLE_PG_TYPE=postgres
DB_TARGET_SAMPLE_PG_HOST=localhost
DB_TARGET_SAMPLE_PG_PORT=5432
DB_TARGET_SAMPLE_PG_USER=postgres
DB_TARGET_SAMPLE_PG_PASSWORD=secret
DB_TARGET_SAMPLE_PG_DATABASE=my_database
"""


class InitController:
    """Handles the 'init' CLI command."""

    def execute(self, fmt: str = "yaml", force: bool = False) -> Dict[str, Any]:
        target_filename = "irides.yaml" if fmt == "yaml" else ".env"
        target_path = Path(target_filename)

        if target_path.exists() and not force:
            raise ValueError(
                f"'{target_filename}' already exists. Use --force to overwrite."
            )

        content = SAMPLE_YAML if fmt == "yaml" else SAMPLE_ENV
        target_path.write_text(content, encoding="utf-8")

        return {
            "status": "created",
            "file": target_filename,
            "message": f"Template created at '{target_filename}'. Edit your database credentials and run 'irides configurations'.",
        }
