from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.persistence import store
from app.bot import wiring


BASE_SIGNAL = "gold sell 4100-4105 / sl 4110 / tp 95/90/80"


def _dm(text: str, user_id: int = 42) -> SimpleNamespace:
  return SimpleNamespace(
    text=text,
    from_user=SimpleNamespace(id=user_id),
    answer=AsyncMock(),
  )


@pytest.fixture
def incident_messages() -> list[tuple[str, str, int]]:
  return [
    (
      "gold sell entry zone (4087-4090) / sl 4095 "
      "/ tp 78/66/59/48 /  golden-fib **",
      "golden-fib",
      2,
    ),
    (
      "gold sell entry zone (4087-4090) / sl 4095 "
      "/ tp 83/80/73/68/58 resistance-zone *",
      "resistance-zone",
      1,
    ),
  ]


@pytest.mark.parametrize(
  ("suffix", "setup_type", "confluence"),
  [
    (" / setup golden-fib **", "golden-fib", 2),
    (" / golden-fib **", "golden-fib", 2),
    (" golden-fib **", "golden-fib", 2),
    (" / setup golden-fib 2", "golden-fib", 2),
    (" resistance-zone *", "resistance-zone", 1),
    (" / golden-fib", "golden-fib", None),
  ],
)
def test_lenient_setup_suffix_forms(
  suffix,
  setup_type,
  confluence,
):
  parsed = wiring._parse_manual(BASE_SIGNAL + suffix)

  assert parsed is not None
  assert parsed["setup_type"] == setup_type
  assert parsed["confluence"] == confluence


def test_real_incident_messages_parse_setup_tags(incident_messages):
  for text, setup_type, confluence in incident_messages:
    parsed = wiring._parse_manual(text)

    assert parsed is not None
    assert parsed["setup_type"] == setup_type
    assert parsed["confluence"] == confluence


@pytest.mark.parametrize(
  "suffix",
  [" vip", " scalp", " sl", " 4048", " chờ London"],
)
def test_setup_suffix_guards_leave_trade_fields_intact(suffix):
  parsed = wiring._parse_manual(BASE_SIGNAL + suffix)

  assert parsed is not None
  assert parsed["setup_type"] is None
  assert parsed["confluence"] is None
  assert parsed["action"] == "SELL"
  assert parsed["entry"] == pytest.approx(4100)
  assert parsed["entry_end"] == pytest.approx(4105)
  assert parsed["sl"] == pytest.approx(4110)
  assert parsed["tps"] == [4095, 4090, 4080]


def test_setup_suffix_interacts_with_vip_and_scalp_options():
  tagged_vip = wiring._parse_manual(
    BASE_SIGNAL + " / setup golden-fib ** / vip"
  )
  scalp = wiring._parse_manual(BASE_SIGNAL + " / scalp")

  assert tagged_vip is not None
  assert tagged_vip["setup_type"] == "golden-fib"
  assert tagged_vip["confluence"] == 2
  assert tagged_vip["visibility"] == "vip"
  assert scalp is not None
  assert scalp["setup_type"] == "scalp"
  assert scalp["confluence"] is None


def test_manual_signal_without_trailing_tag_is_unchanged():
  parsed = wiring._parse_manual(BASE_SIGNAL)

  assert parsed is not None
  assert parsed["setup_type"] is None
  assert parsed["confluence"] is None
  assert parsed["visibility"] == "both"
  assert parsed["risk"] == pytest.approx(10)


async def _prepare_manual_send(monkeypatch):
  monkeypatch.setattr(wiring.settings, "telegram_owner_id", 42)
  monkeypatch.setattr(
    wiring,
    "event_in_window",
    AsyncMock(return_value=None),
  )
  monkeypatch.setattr(
    wiring,
    "store_manual_signal",
    AsyncMock(return_value={"id": 47, "daily_seq": 1}),
  )
  monkeypatch.setattr(
    wiring,
    "get_manual_signal",
    AsyncMock(return_value={"id": 47}),
  )
  monkeypatch.setattr(wiring, "broadcast_entry", AsyncMock())


@pytest.mark.asyncio
async def test_manual_send_confirmation_echoes_setup_and_stars(monkeypatch):
  await _prepare_manual_send(monkeypatch)
  msg = _dm(BASE_SIGNAL + " / golden-fib **")

  await wiring.handle_private_signal(msg)

  assert msg.answer.await_args.args[0] == (
    "✅ Sent to channel (#1) · setup golden-fib ⭐⭐"
  )


@pytest.mark.asyncio
async def test_manual_send_confirmation_warns_when_setup_is_missing(monkeypatch):
  await _prepare_manual_send(monkeypatch)
  msg = _dm(BASE_SIGNAL)

  await wiring.handle_private_signal(msg)

  text = msg.answer.await_args.args[0]
  assert "✅ Sent to channel (#1)" in text
  assert "⚠️ no setup tag" in text
  assert "tag #1 &lt;setup&gt; **" in text


@pytest.mark.asyncio
async def test_trade_untagged_lists_only_null_setup_newest_first(monkeypatch):
  monkeypatch.setattr(wiring.settings, "telegram_owner_id", 42)
  await store.init_db()
  older = await store.store_manual_signal(
    100, "SELL", 4087, 4090, 4095, [4078], setup_type=None,
  )
  tagged = await store.store_manual_signal(
    200, "BUY", 4021, 4025, 4015, [4030], setup_type="golden-fib",
  )
  newer = await store.store_manual_signal(
    300, "BUY", 4031, 4035, 4020, [4040], setup_type=None,
  )
  await store.close_manual_signal(older["id"], 80)
  await store.close_manual_signal(newer["id"], -30)
  msg = _dm("/trade_untagged")

  await wiring.handle_trade_untagged(msg)

  text = msg.answer.await_args.args[0]
  assert "Untagged signals (2)" in text
  assert f"id:{tagged['id']}" not in text
  assert text.index(f"id:{newer['id']}") < text.index(f"id:{older['id']}")
  assert f"id:{newer['id']}" in text and "-30p" in text
  assert f"id:{older['id']}" in text and "+80p" in text
  assert f"/trade_tag id:{newer['id']} &lt;setup&gt; **" in text


@pytest.mark.asyncio
async def test_trade_untagged_is_owner_gated(monkeypatch):
  monkeypatch.setattr(wiring.settings, "telegram_owner_id", 42)
  get_untagged = AsyncMock()
  monkeypatch.setattr(wiring, "get_untagged_signals", get_untagged)
  msg = _dm("/trade_untagged", user_id=99)

  await wiring.handle_trade_untagged(msg)

  get_untagged.assert_not_awaited()
  msg.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_trade_untagged_defaults_to_twenty(monkeypatch):
  monkeypatch.setattr(wiring.settings, "telegram_owner_id", 42)
  get_untagged = AsyncMock(return_value=[])
  monkeypatch.setattr(wiring, "get_untagged_signals", get_untagged)
  msg = _dm("/trade_untagged")

  await wiring.handle_trade_untagged(msg)

  get_untagged.assert_awaited_once_with(20)
  assert msg.answer.await_args.args[0] == "✅ No untagged signals."


@pytest.mark.asyncio
async def test_trade_tag_absolute_id_is_owner_gated(monkeypatch):
  monkeypatch.setattr(wiring.settings, "telegram_owner_id", 42)
  get_signal = AsyncMock()
  monkeypatch.setattr(wiring, "get_manual_signal", get_signal)
  msg = _dm("/trade_tag id:47 golden-fib **", user_id=99)

  await wiring.handle_trade_tag(msg)

  get_signal.assert_not_awaited()
  msg.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_trade_tag_absolute_id_updates_closed_signal_and_backfill(monkeypatch):
  monkeypatch.setattr(wiring.settings, "telegram_owner_id", 42)
  await store.init_db()
  untouched = await store.store_manual_signal(
    100, "SELL", 4087, 4090, 4095, [4078], setup_type=None,
  )
  target = await store.store_manual_signal(
    200, "BUY", 4021, 4025, 4015, [4030], setup_type=None,
  )
  await store.close_manual_signal(target["id"], 50)
  monkeypatch.setattr(
    wiring,
    "post_result",
    AsyncMock(return_value="tagged"),
  )
  msg = _dm(f"/trade_tag id:{target['id']} golden-fib **")

  await wiring.handle_trade_tag(msg)

  row = await store.get_manual_signal(target["id"])
  assert row["status"] == "closed"
  assert row["setup_type"] == "golden-fib"
  assert row["confluence"] == 2
  remaining = await store.get_untagged_signals()
  assert [signal["id"] for signal in remaining] == [untouched["id"]]
