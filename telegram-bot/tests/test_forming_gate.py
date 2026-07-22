from datetime import datetime, timezone

import pandas as pd
import pytest

from app.analysis import scanner
from app.analysis.detectors import DetectionResult
from app.analysis.market_map import MarketMap, ScalpRail
from app.analysis.types import Zone
from app.autotrade.forming_gate import (
  FORMING_GATE_VERSION,
  FormingRail,
  FormingRangeSetup,
  evaluate_forming_range_gate,
  forming_gate_key,
  forming_range_id,
  forming_setup_id,
)
from app.persistence import redis_state


NOW = int(datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc).timestamp())


def _rail(direction: str, level: float) -> FormingRail:
  return FormingRail(
    direction,
    level - 0.2,
    level + 0.2,
    level,
    9.0,
    ("micro ×4", "wick ×3"),
  )


def _setup(**changes) -> FormingRangeSetup:
  values = {
    "version": FORMING_GATE_VERSION,
    "setup_id": forming_setup_id("XAU", "M5", "1784721300", "BUY", 4113, 4122),
    "range_id": forming_range_id("XAU", 4113, 4122),
    "symbol": "XAU",
    "source_tf": "M5",
    "event_ts": "1784721300",
    "issued_at": NOW,
    "expires_at": NOW + 420,
    "setup": "Range Edge Scalp",
    "mode": "range_scalp",
    "direction": "BUY",
    "m5_confirmation": "sweep_reclaim",
    "key_level": 4113.0,
    "entry_low": 4112.8,
    "entry_high": 4113.4,
    "confluence": 2,
    "reasons": ("local range", "wick rejection"),
    "lower": _rail("BUY", 4113.0),
    "upper": _rail("SELL", 4122.0),
    "map_bias": "up",
    "map_bias_tf": "M30",
  }
  values.update(changes)
  return FormingRangeSetup(**values)


def _frames(
  *,
  rejection: bool = True,
  broken: bool = False,
  m5_touch: bool = True,
):
  index = pd.date_range("2026-07-22 11:40", periods=20, freq="1min", tz="UTC")
  rows = [{
    "open": 4114.0,
    "high": 4114.6,
    "low": 4113.6,
    "close": 4114.1,
  } for _ in index]
  if rejection:
    rows[-1] = {
      "open": 4113.1,
      "high": 4114.0,
      "low": 4112.7,
      "close": 4113.8,
    }
  if broken:
    rows[-2] = {
      "open": 4111.7,
      "high": 4111.8,
      "low": 4111.0,
      "close": 4111.2,
    }
    rows[-1] = {
      "open": 4111.2,
      "high": 4111.4,
      "low": 4110.7,
      "close": 4110.9,
    }
  m1 = pd.DataFrame(rows, index=index)
  m5_index = pd.date_range("2026-07-22 10:00", periods=20, freq="5min", tz="UTC")
  m5 = pd.DataFrame({
    "open": [4116.0] * 20,
    "high": [4121.5] * 20,
    "low": [4113.1 if m5_touch else 4115.0] * 20,
    "close": [4116.0] * 20,
  }, index=m5_index)
  if m5_touch:
    m5.iloc[-1] = {
      "open": 4114.0,
      "high": 4116.0,
      "low": 4112.6,
      "close": 4114.0,
    }
  return {"M1": m1, "M5": m5, "M15": m5.copy()}


def _map() -> MarketMap:
  return MarketMap(
    [],
    4113.8,
    4117.5,
    4113.0,
    4122.0,
    "up",
    "M30",
    rails=[
      ScalpRail(4113.0, 4112.8, 4113.2, 4113, "BUY", ["micro ×4"], 9),
      ScalpRail(4122.0, 4121.8, 4122.2, 4122, "SELL", ["micro ×5"], 10),
    ],
  )


def _result(direction: str = "BUY", low: float = 4112.8, high: float = 4113.4):
  return DetectionResult(
    "Range Edge Scalp",
    direction,
    4113.0 if direction == "BUY" else 4122.0,
    Zone(low, high, "demand" if direction == "BUY" else "supply"),
    4113.8,
    2,
    ["local range", "wick rejection"],
    mode="range_scalp",
    confirmation="sweep_reclaim",
  )


def test_forming_contract_round_trips_and_rejects_wrong_version():
  setup = _setup()

  assert FormingRangeSetup.from_json(setup.to_json()) == setup
  assert FormingRangeSetup.from_json("not-json") is None
  assert FormingRangeSetup.from_json(
    _setup(version=FORMING_GATE_VERSION + 1).to_json()
  ) is None


def test_scanner_builds_intent_only_when_forming_setup_overlaps_map_rail(
  monkeypatch,
):
  monkeypatch.setattr(scanner.settings, "auto_trade_forming_max_age_seconds", 420)

  setup = scanner._build_forming_range_setup(
    "XAU", "M5", "1784721300", [_result()], _map(), now=NOW,
  )
  mismatch = scanner._build_forming_range_setup(
    "XAU", "M5", "1784721300", [_result(low=4116, high=4117)], _map(), now=NOW,
  )
  wrong_setup = scanner._build_forming_range_setup(
    "XAU",
    "M5",
    "1784721300",
    [DetectionResult(
      "Momentum Ride",
      "BUY",
      4113,
      Zone(4112.8, 4113.4, "demand"),
      4113.8,
      3,
      [],
    )],
    _map(),
    now=NOW,
  )

  assert setup is not None
  assert setup.direction == "BUY"
  assert setup.range_id == forming_range_id("XAU", 4113, 4122)
  assert setup.lower.level == 4113.0
  assert setup.upper.level == 4122.0
  assert setup.expires_at == NOW + 420
  assert mismatch is None
  assert wrong_setup is None


@pytest.mark.asyncio
async def test_scanner_syncs_and_clears_short_lived_forming_intent(monkeypatch):
  client = redis_state.get_client()
  monkeypatch.setattr(scanner.settings, "auto_trade_forming_gate_enabled", True)
  monkeypatch.setattr(scanner.settings, "auto_trade_forming_max_age_seconds", 420)

  setup = await scanner._sync_forming_gate(
    client, "XAU", "M5", "1784721300", [_result()], _map(),
  )

  assert setup is not None
  assert FormingRangeSetup.from_json(
    await client.get(forming_gate_key("XAU"))
  ) == setup

  assert await scanner._sync_forming_gate(
    client, "XAU", "M5", "1784721600", [], _map(),
  ) is None
  assert await client.get(forming_gate_key("XAU")) is None


def test_forming_gate_requires_recent_m1_rejection():
  decision = evaluate_forming_range_gate(
    _frames(rejection=False),
    _setup(),
    symbol="XAU",
    spot_price=4113.8,
    now=NOW + 60,
  )

  assert decision.state == "forming_waiting_m1"
  assert decision.direction == "BUY"
  assert decision.box is not None
  assert decision.box.lower.level == 4113.0
  assert decision.box.upper.level == 4122.0
  assert "M5 structure sweep reclaim" in decision.reasons


def test_forming_gate_waits_when_m5_no_longer_touches_structure():
  decision = evaluate_forming_range_gate(
    _frames(m5_touch=False),
    _setup(),
    symbol="XAU",
    spot_price=4113.8,
    now=NOW + 60,
  )

  assert decision.state == "forming_waiting_m5"
  assert decision.direction == "BUY"
  assert "waiting for M5 structure hold" in decision.reasons[-1]


def test_forming_gate_emits_map_aligned_candidate_with_full_tp():
  decision = evaluate_forming_range_gate(
    _frames(),
    _setup(),
    symbol="XAU",
    spot_price=4113.8,
    now=NOW + 60,
  )

  assert decision.state == "candidate"
  assert decision.direction == "BUY"
  assert decision.trigger == "range_rejection"
  assert decision.full_tp_pips == 70
  assert decision.target_room_pips == pytest.approx(80.0)
  assert decision.box is not None
  assert decision.box.box_id == forming_range_id("XAU", 4113, 4122)
  assert "Market Map M5 range aligned" in decision.reasons
  assert "M5 sweep_reclaim + sweep reclaim" in decision.reasons


def test_forming_gate_fails_closed_when_stale_moved_or_broken():
  stale = evaluate_forming_range_gate(
    _frames(), _setup(), symbol="XAU", spot_price=4113.8, now=NOW + 421,
  )
  moved = evaluate_forming_range_gate(
    _frames(), _setup(), symbol="XAU", spot_price=4114.3, now=NOW + 60,
  )
  broken = evaluate_forming_range_gate(
    _frames(broken=True), _setup(), symbol="XAU", spot_price=4112.0, now=NOW + 60,
  )

  assert stale.state == "forming_stale"
  assert moved.state == "entry_moved"
  assert broken.state == "box_broken"
