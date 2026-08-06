import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "data", "ryukomik.db")
db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row

rows = db.execute("SELECT staff_id, username, avatar FROM dashboard_staff_cache").fetchall()
print("STAFF CACHE:")
for r in rows:
    print(dict(r))

db_dashboard = sqlite3.connect(os.path.join(os.path.dirname(__file__), "data", "staff_pay.db"))
db_dashboard.row_factory = sqlite3.Row
rows2 = db_dashboard.execute("SELECT * FROM manual_bonuses").fetchall()
print("\nMANUAL BONUSES:")
for r in rows2:
    print(dict(r))
