import sqlite3
from pathlib import Path

db_path = Path('/mnt/c/10_Project/BaroLab/dashboard/data/memory_graph.sqlite3')
if db_path.exists():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print('Tables in memory_graph.sqlite3:', tables)
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]} rows")
