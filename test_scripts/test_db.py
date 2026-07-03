import sqlite3
import json

conn = sqlite3.connect('data/signals.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM manual_signals ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
if row:
    print(dict(row))
else:
    print("No signals found.")
