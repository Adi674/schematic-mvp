"""
Database seeding script.
Validates data/rules/rules_source.json via Pydantic and loads into SQLite data/rules/rules.db.
"""

import os
import json
import sqlite3
from typing import Optional, List
from pydantic import BaseModel, Field


class RuleRecord(BaseModel):
    rule_id: str
    domain: str
    rule_category: str
    symbol: str
    pin: str
    min_value_SI: Optional[float] = None
    max_value_SI: Optional[float] = None
    unit: str
    dielectric_required: Optional[str] = None
    voltage_rating_min_V: Optional[float] = None
    related_symbols: List[str] = Field(default_factory=list)
    formula_expression: Optional[str] = None
    source_table: str
    source_page: int
    source_chunk_id: str
    approved_by: Optional[str] = "Human Reviewer"
    source_doc_version: Optional[str] = "TLE987x_HW_Guideline_Rev1.1"


def create_and_seed_rules_db(json_path: str, db_path: str):
    """Reads json_path, validates rules, creates SQLite schema and seeds DB."""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Source rules file not found at: {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Validate each rule using Pydantic
    rules: List[RuleRecord] = [RuleRecord(**item) for item in data]
    print(f"Validated {len(rules)} rules cleanly via Pydantic.")

    # Create / overwrite SQLite DB
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create schema
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rules (
        rule_id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        rule_category TEXT NOT NULL,
        symbol TEXT NOT NULL,
        pin TEXT NOT NULL,
        min_value_SI REAL,
        max_value_SI REAL,
        unit TEXT NOT NULL,
        dielectric_required TEXT,
        voltage_rating_min_V REAL,
        related_symbols TEXT,
        formula_expression TEXT,
        source_table TEXT NOT NULL,
        source_page INTEGER NOT NULL,
        source_chunk_id TEXT NOT NULL,
        approved_by TEXT,
        source_doc_version TEXT
    );
    """)

    # Create index for O(1) lookups by symbol, pin, or domain
    cursor.execute("CREATE INDEX idx_rules_symbol ON rules(symbol);")
    cursor.execute("CREATE INDEX idx_rules_pin ON rules(pin);")
    cursor.execute("CREATE INDEX idx_rules_domain ON rules(domain);")

    # Insert records
    for r in rules:
        cursor.execute("""
        INSERT INTO rules (
            rule_id, domain, rule_category, symbol, pin,
            min_value_SI, max_value_SI, unit, dielectric_required, voltage_rating_min_V,
            related_symbols, formula_expression, source_table, source_page, source_chunk_id,
            approved_by, source_doc_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            r.rule_id, r.domain, r.rule_category, r.symbol, r.pin,
            r.min_value_SI, r.max_value_SI, r.unit, r.dielectric_required, r.voltage_rating_min_V,
            json.dumps(r.related_symbols), r.formula_expression, r.source_table, r.source_page, r.source_chunk_id,
            r.approved_by, r.source_doc_version
        ))

    conn.commit()
    conn.close()
    print(f"Successfully seeded {len(rules)} rules into {db_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source_json = os.path.join(base_dir, "data", "rules", "rules_source.json")
    target_db = os.path.join(base_dir, "data", "rules", "rules.db")
    create_and_seed_rules_db(source_json, target_db)
