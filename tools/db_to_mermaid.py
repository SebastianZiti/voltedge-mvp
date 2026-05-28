import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parent.parent / "voltedge.db"


def schema_to_mermaid(db_path):
    if not db_path.exists():
        raise FileNotFoundError(f"Database findes ikke: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]

    lines = ["erDiagram"]

    for table in tables:
        lines.append(f"    {table} {{")
        for col in conn.execute(f"PRAGMA table_info({table})"):
            col_type = (col["type"] or "TEXT").lower().replace(" ", "_")
            marker = " PK" if col["pk"] else ""
            lines.append(f"        {col_type} {col['name']}{marker}")
        lines.append("    }")

    for table in tables:
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
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
