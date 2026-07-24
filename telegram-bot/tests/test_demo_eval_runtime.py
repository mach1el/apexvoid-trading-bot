import json
from types import SimpleNamespace

import fakeredis
import pytest

from app.autotrade.config_health import compare_manifests
from app.autotrade.config_health import publish_python_manifest
from app.autotrade.gate import AutoScalpDecision
from app.autotrade.lifecycle import emit_lifecycle
from app.autotrade.range_context import (
  RangeBarrier,
  RangeContext,
  resolve_range_context,
)
from app.core.config import Settings
from app.autotrade import config_health, worker


def _settings(monkeypatch, **env):
  monkeypatch.setenv(
    "TELEGRAM_BOT_TOKEN",
    "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
  )
  monkeypatch.setenv("SIGNAL_VIP_CHANNEL_ID", "-100123456789")
  monkeypatch.setenv("AUTO_TRADE_PROFILE", "demo_eval")
  for key, value in env.items():
    monkeypatch.setenv(key, str(value))
  return Settings(_env_file=None)


def test_demo_profile_resolves_execution_defaults(monkeypatch):
  cfg = _settings(monkeypatch)
  assert cfg.auto_trade_profile == "demo_eval"
  assert cfg.auto_trade_require_demo_account
  assert cfg.auto_trade_allow_concurrent_strategies
  assert cfg.auto_trade_allow_hedged_xau
  assert not cfg.auto_trade_require_flat_for_range
  assert cfg.auto_trade_range_two_sided_enabled
  assert cfg.auto_trade_range_flip_enabled
  assert cfg.auto_trade_multi_match_enabled
  assert cfg.auto_trade_track_all_structural_matches
  assert cfg.scanner_top_n == 0
  assert cfg.auto_trade_max_tracked_candidates == 0


def test_demo_profile_does_not_override_explicit_environment(monkeypatch):
  cfg = _settings(
    monkeypatch,
    AUTO_TRADE_RANGE_FLIP_ENABLED="false",
    AUTO_TRADE_ALLOW_HEDGED_XAU="false",
    SCANNER_TOP_N="7",
  )
  assert not cfg.auto_trade_range_flip_enabled
  assert not cfg.auto_trade_allow_hedged_xau
  assert cfg.scanner_top_n == 7


def test_demo_profile_cannot_disable_demo_account_guard(monkeypatch):
  with pytest.raises(ValueError, match="requires.*DEMO_ACCOUNT"):
    _settings(
      monkeypatch,
      AUTO_TRADE_REQUIRE_DEMO_ACCOUNT="false",
    )


def _context(source, lower, upper, quality=5.0):
  return RangeContext(
    version=1,
    range_id=f"{source}-{lower}-{upper}",
    symbol="XAU",
    state="confirmed",
    source=source,
    execution_timeframe="M1",
    context_timeframes=("M1", "M5"),
    lower=lower,
    upper=upper,
    equilibrium=(lower + upper) / 2,
    width_price=upper - lower,
    width_pips=(upper - lower) / 0.1,
    width_atr=(upper - lower) / 2,
    lower_barrier=RangeBarrier(
      lower, lower - 0.1, lower + 0.1, 3, 2,
    ),
    upper_barrier=RangeBarrier(
      upper, upper - 0.1, upper + 0.1, 3, 2,
    ),
    supports=(RangeBarrier(lower, lower, lower, 3, 2),),
    resistances=(RangeBarrier(upper, upper, upper, 3, 2),),
    inside_close_count=12,
    quality=quality,
    generated_at=100,
    expires_at=1000,
  )


def test_compatible_scanner_and_private_ranges_merge():
  resolved, comparison = resolve_range_context(
    _context("scanner", 4000, 4010),
    _context("private", 4000.5, 4009.5),
    now=200,
  )
  assert resolved is not None
  assert resolved.source == "merged"
  assert comparison["resolution"] == "merged"
  assert not comparison["disagreement"]


def test_material_range_disagreement_is_recorded_deterministically():
  scanner = _context("scanner", 4000, 4010, quality=8)
  private = _context("private", 4020, 4030, quality=3)
  resolved, comparison = resolve_range_context(scanner, private, now=200)
  assert resolved == scanner
  assert comparison["disagreement"]
  assert comparison["reason"] == "materially_incompatible_geometry"


def test_accepted_breakout_retires_range_over_stale_active_source():
  scanner = _context("scanner", 4000, 4010, quality=8)
  broken = RangeContext(
    **{
      **scanner.__dict__,
      "range_id": "private-broken",
      "source": "private",
      "state": "broken",
      "breakout_state": "accepted",
      "invalidation_reason": "accepted_structural_breakout",
      "generated_at": 150,
    }
  )
  resolved, comparison = resolve_range_context(
    scanner,
    broken,
    now=200,
  )
  assert resolved == broken
  assert comparison["resolution"] == "accepted_structural_breakout"
  assert comparison["disagreement"]


@pytest.mark.asyncio
async def test_lifecycle_keeps_history_not_only_latest(monkeypatch):
  client = fakeredis.FakeAsyncRedis(decode_responses=True)
  monkeypatch.setattr(
    "app.autotrade.lifecycle.settings",
    SimpleNamespace(
      auto_trade_profile="demo_eval",
      auto_trade_candidate_ttl=86400,
      auto_trade_event_stream="auto_trade:events",
      auto_trade_stream_maxlen=1000,
    ),
  )
  await emit_lifecycle(
    client, "detected", symbol="XAU", candidate_id="candidate-1",
  )
  await emit_lifecycle(
    client, "auto_ready", symbol="XAU", candidate_id="candidate-1",
  )
  history = await client.lrange(
    "auto_trade:lifecycle:candidate-1", 0, -1,
  )
  assert [json.loads(item)["state"] for item in history] == [
    "detected", "auto_ready",
  ]


@pytest.mark.asyncio
async def test_both_range_rails_stay_independent(monkeypatch):
  client = fakeredis.FakeAsyncRedis(decode_responses=True)
  context = _context("merged", 4000, 4010)
  decision = AutoScalpDecision("candidate", direction="BUY")
  monkeypatch.setattr(
    worker.settings, "auto_trade_box_retire_seconds", 14400,
  )

  await worker._persist_range_side_states(
    client,
    symbol="XAU",
    context=context,
    decision=decision,
  )
  buy_key = (
    f"auto_trade:range_side:XAU:{context.range_id}:BUY"
  )
  sell_key = (
    f"auto_trade:range_side:XAU:{context.range_id}:SELL"
  )
  buy = json.loads(await client.get(buy_key))
  sell = json.loads(await client.get(sell_key))
  assert buy["state"] == "CONFIRMED"
  assert sell["state"] == "ARMED"

  await worker._mark_range_side_candidate(
    client,
    symbol="XAU",
    range_id=context.range_id,
    direction="BUY",
    candidate_id="buy-candidate",
  )
  await client.set(
    worker._box_edge_key("XAU", context.range_id, "BUY"), "1",
  )
  await worker._persist_range_side_states(
    client,
    symbol="XAU",
    context=context,
    decision=AutoScalpDecision("candidate", direction="SELL"),
  )
  buy = json.loads(await client.get(buy_key))
  sell = json.loads(await client.get(sell_key))
  assert buy["state"] == "CANDIDATE_PUBLISHED"
  assert buy["candidate_id"] == "buy-candidate"
  assert sell["state"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_python_config_manifest_is_published(monkeypatch):
  client = fakeredis.FakeAsyncRedis(decode_responses=True)
  cfg = _settings(monkeypatch)
  monkeypatch.setattr(config_health, "settings", cfg)

  health = await publish_python_manifest(client)

  manifest = json.loads(
    await client.get("auto_trade:config_manifest:python")
  )
  assert manifest["profile"] == "demo_eval"
  assert manifest["two_sided_range"]
  assert manifest["concurrent_strategies"]
  assert health["state"] == "warning"
  assert health["warnings"] == ["ctrader_manifest_missing"]


def test_config_health_detects_fatal_contract_mismatch():
  python = {
    "candidate_stream": "auto_trade:candidates",
    "redis_database": 0,
    "redis_fingerprint": "same",
    "canonical_symbol": "XAU",
    "pip_size": 0.1,
    "candidate_contract_version": 4,
    "target_plans": [30, 60],
    "range_target_plans": [20, 30],
  }
  ctrader = {
    **python,
    "pip_size": 0.01,
  }
  health = compare_manifests(python, ctrader)
  assert health["state"] == "fatal"
  assert "pip_size" in health["fatal"]
