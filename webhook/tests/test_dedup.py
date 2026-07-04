import os
import json
import sqlite3

import pytest

os.environ.setdefault(
  "TELEGRAM_BOT_TOKEN",
  "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
)
os.environ.setdefault("TELEGRAM_CHAT_ID", "-100123456789")

from app import dedup


@pytest.mark.asyncio
async def test_daily_seq_resets_by_trade_date(tmp_path, monkeypatch):
  db_path = tmp_path / "signals.db"
  monkeypatch.setattr(dedup.settings, "db_path", str(db_path))
  await dedup.init_db()

  first = await dedup.store_manual_signal(
    1, "BUY", 2000.0, 2002.0, 1990.0, [2010.0],
  )
  second = await dedup.store_manual_signal(
    2, "SELL", 2000.0, 2002.0, 2010.0, [1990.0],
  )
  assert first["daily_seq"] == 1
  assert second["daily_seq"] == 2

  db = sqlite3.connect(db_path)
  db.execute("UPDATE manual_signals SET trade_date = '2000-01-01'")
  db.commit()
  db.close()

  next_day = await dedup.store_manual_signal(
    3, "BUY", 2000.0, 2002.0, 1990.0, [2010.0],
  )
  assert next_day["daily_seq"] == 1


@pytest.mark.asyncio
async def test_legacy_schema_migrates_and_fill_is_idempotent(
  tmp_path,
  monkeypatch,
):
  db_path = tmp_path / "legacy.db"
  db = sqlite3.connect(db_path)
  db.execute(
    """
    CREATE TABLE manual_signals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      action TEXT NOT NULL,
      entry REAL NOT NULL,
      entry_end REAL,
      sl REAL NOT NULL,
      tps TEXT NOT NULL,
      order_type TEXT NOT NULL,
      channel_message_id INTEGER,
      status TEXT NOT NULL DEFAULT 'open',
      result_pips INTEGER,
      closed_at INTEGER
    )
    """
  )
  db.execute(
    "INSERT INTO manual_signals "
    "(ts, action, entry, entry_end, sl, tps, order_type) "
    "VALUES (1, 'BUY', 2000, 2002, 1990, '[2010]', 'zone')"
  )
  db.commit()
  db.close()

  monkeypatch.setattr(dedup.settings, "db_path", str(db_path))
  await dedup.init_db()

  db = sqlite3.connect(db_path)
  columns = {
    row[1] for row in db.execute("PRAGMA table_info(manual_signals)")
  }
  db.close()
  assert {
    "daily_seq", "trade_date", "fill_state", "filled_at", "legs",
    "parent_id", "setup_type", "confluence", "note", "symbol",
    "visibility",
  } <= columns

  assert await dedup.mark_filled(1) is not None
  assert await dedup.mark_filled(1) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
  ("runner_pips", "expected_net"),
  [(90, 70), (-30, 10)],
)
async def test_close_leg_weighted_net(
  tmp_path,
  monkeypatch,
  runner_pips,
  expected_net,
):
  db_path = tmp_path / "weighted.db"
  monkeypatch.setattr(dedup.settings, "db_path", str(db_path))
  await dedup.init_db()
  rec = await dedup.store_manual_signal(
    1, "BUY", 2000.0, 2002.0, 1990.0, [2010.0],
  )

  partial = await dedup.close_leg(rec["id"], 50, 0.5)
  assert partial["closed"] is False
  assert partial["remaining"] == pytest.approx(0.5)

  final = await dedup.close_leg(rec["id"], runner_pips)
  assert final["closed"] is True
  assert final["net"] == expected_net

  db = sqlite3.connect(db_path)
  status, result_pips, legs_json = db.execute(
    "SELECT status, result_pips, legs FROM manual_signals WHERE id = ?",
    (rec["id"],),
  ).fetchone()
  db.close()
  assert status == "closed"
  assert result_pips == expected_net
  assert len(json.loads(legs_json)) == 2


@pytest.mark.asyncio
async def test_close_leg_rejects_overbook(tmp_path, monkeypatch):
  db_path = tmp_path / "overbook.db"
  monkeypatch.setattr(dedup.settings, "db_path", str(db_path))
  await dedup.init_db()
  rec = await dedup.store_manual_signal(
    1, "BUY", 2000.0, 2002.0, 1990.0, [2010.0],
  )

  await dedup.close_leg(rec["id"], 50, 0.5)
  rejected = await dedup.close_leg(rec["id"], 40, 0.6)

  assert rejected["error"] == "exceeds_remaining"
  assert rejected["remaining"] == pytest.approx(0.5)
  open_signal = (await dedup.get_open_signals())[0]
  assert len(open_signal["legs"]) == 1
