"""
Genererer et Mermaid ER-diagram fra voltedge.db's faktiske skema.

Brug:
    python tools/db_to_mermaid.py                  # printer til terminal
    python tools/db_to_mermaid.py > er_diagram.md  # gemmer til fil

Pasta output'et i:
    - https://mermaid.live   (instant preview, eksporter PNG/SVG)
    - VS Code med Markdown Preview Mermaid Support extension
    - GitHub README - Mermaid renderes automatisk

Diagrammet afspejler ALTID den faktiske DB - kor det igen efter skema-aendringer.
"""
import sqlite3
import sys
from pathlib import Path


# Default-sti til den lokale DB. Kan overrides med foerste argument paa
# kommandolinjen, fx: python tools/db_to_mermaid.py path/to/anden.db
DEFAULT_DB = Path(__file__).resolve().parent.parent / "voltedge.db"


def schema_to_mermaid(db_path):
    """Laeser SQLite-skemaet og bygger Mermaid ER-syntaks."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database findes ikke: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 1) Find alle bruger-tabeller (ikke sqlite_*-systemtabeller).
    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]

    lines = ["erDiagram"]

    # 2) For hver tabel: list kolonner med type + PK-marker.
    for table in tables:
        lines.append(f"    {table} {{")
        for col in conn.execute(f"PRAGMA table_info({table})"):
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            col_type = (col["type"] or "TEXT").lower().replace(" ", "_")
            marker = " PK" if col["pk"] else ""
            lines.append(f"        {col_type} {col['name']}{marker}")
        lines.append("    }")

    # 3) Find fremmednoegler og tegn relationer.
    # I Mermaid ER: forael ||--o{ barn betyder "én forael har mange barn".
    # En FK paa barn.charger_id der peger paa chargers.id giver:
    #   chargers ||--o{ telemetry : "has"
    for table in tables:
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
            # PRAGMA foreign_key_list: (id, seq, table, from, to, on_update, on_delete, match)
            parent = fk["table"]
            lines.append(f'    {parent} ||--o{{ {table} : "has"')

    conn.close()
    return "\n".join(lines)


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    mermaid = schema_to_mermaid(db_path)
    print("```mermaid")
    print(mermaid)
    print("```")


if __name__ == "__main__":
    main()
