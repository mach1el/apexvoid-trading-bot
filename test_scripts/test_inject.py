import sqlite3
import time

conn = sqlite3.connect('/root/Projects/signal-bot/data/signals.db')
cur = conn.cursor()
ts = int(time.time())

cur.execute("""
INSERT INTO manual_signals (
    ts, action, entry, entry_end, sl, tps, order_type, 
    channel_message_id, status, fill_state, tps_hit, trade_date, daily_seq, legs
) VALUES (
    ?, 'BUY', 4160.0, 4162.0, 4100.0, '[4170.0, 4180.0, 4190.0]', 'market',
    160, 'open', 'filled', '[]', '2026-07-03', 99, '[]'
)
""", (ts,))
conn.commit()
print("Inserted dummy signal successfully.")
