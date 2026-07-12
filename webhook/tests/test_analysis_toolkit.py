import pandas as pd

from app.analysis import (
  AnalysisSettings,
  TimeframeAnalysis,
  _apply_mtf_zone_scores,
  _htf_bias,
  analyze,
)
from app.levels import key_levels
from app.liquidity import liquidity_grabs, liquidity_pools
from app.momentum import momentum
from app.pa_types import Break, Leg, Level, Pool, Swing, Zone
from app.structure import market_structure, structure_breaks
from app.swings import find_swings
from app.zones import mark_mitigation, merge_zones, order_blocks, score_zones


def _df(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
  index = pd.date_range("2026-07-10", periods=len(rows), freq="5min", tz="UTC")
  return pd.DataFrame(
    rows,
    columns=["open", "high", "low", "close"],
    index=index,
  ).assign(volume=100)


def test_hybrid_swings_alternate_and_filter_subthreshold_wiggle():
  df = _df([
    (100, 101, 99, 100),
    (100, 105, 100, 104),
    (104, 104, 98, 99),
    (99, 108, 103, 107),
    (107, 107.2, 100, 102),
    (102, 111, 104, 110),
    (110, 110.5, 102, 105),
    (105, 112, 105, 111),
  ])
  atr = pd.Series([2.0] * len(df), index=df.index)

  pivots = find_swings(df, fractal_n=1, zigzag_atr_mult=0.5, atr=atr)

  assert [s.kind for s in pivots] == ["high", "low", "high", "low", "high", "low"]
  assert [s.label for s in pivots if s.kind == "high"][-2:] == ["HH", "HH"]

  noisy = _df([
    (100, 101, 99, 100),
    (104.9, 105, 104.9, 105),
    (104.6, 104.8, 104.2, 104.6),
    (104.5, 104.7, 104.5, 104.6),
  ])
  noisy_atr = pd.Series([2.0] * len(noisy), index=noisy.index)

  assert [
    s.kind for s in find_swings(noisy, fractal_n=1, zigzag_atr_mult=1.0, atr=noisy_atr)
  ] == ["high"]


def test_structure_breaks_classify_bos_and_choch_in_uptrend():
  index = pd.date_range("2026-07-10", periods=8, freq="5min", tz="UTC")
  swings = [
    Swing(1, "high", 105, "HH", index[1]),
    Swing(2, "low", 100, "HL", index[2]),
    Swing(3, "high", 110, "HH", index[3]),
    Swing(4, "low", 104, "HL", index[4]),
  ]
  up_df = _df([
    (100, 101, 99, 100),
    (104, 106, 103, 105),
    (101, 102, 99, 100),
    (108, 111, 107, 110),
    (105, 106, 103, 104),
    (110, 112, 109, 111),
  ])
  down_df = _df([
    (100, 101, 99, 100),
    (104, 106, 103, 105),
    (101, 102, 99, 100),
    (108, 111, 107, 110),
    (105, 106, 103, 104),
    (104, 105, 99, 103),
  ])

  assert market_structure(swings) == "up"
  assert any(
    item.kind == "BOS" and item.direction == "up"
    for item in structure_breaks(swings, up_df)
  )
  assert any(
    item.kind == "CHoCH" and item.direction == "down"
    for item in structure_breaks(swings, down_df)
  )


def test_order_block_created_by_bos_and_later_mitigated():
  df = _df([
    (100, 102, 99, 101),
    (101, 102, 98, 99),
    (99, 105, 99, 104),
    (104, 111, 103, 110),
    (110, 112, 100, 101),
  ])
  zones = order_blocks(
    df,
    [Leg(2, 3, "up", 11)],
    [Break("BOS", "up", 108, 3, df.index[3])],
  )

  assert len(zones) == 1
  zone = zones[0]
  assert zone.side == "demand"
  assert zone.bottom == 99
  assert zone.top == 101
  assert zone.break_kind == "BOS"

  stamped = mark_mitigation(zones, df)[0]
  assert stamped.mitigated is True
  assert stamped.touches == 1


def test_mark_mitigation_respects_asof_cutoff():
  df = _df([
    (100, 104, 99, 103),
    (103, 105, 102, 104),
    (104, 106, 100, 105),
  ])
  zone = Zone(100, 101, "demand", origin_index=0, source="order_block")

  as_of_previous = mark_mitigation([zone], df, cutoff=len(df) - 1)[0]
  full_history = mark_mitigation([zone], df)[0]

  assert as_of_previous.touches == 0
  assert as_of_previous.mitigated is False
  assert full_history.touches == 1
  assert full_history.mitigated is True


def test_merge_zones_combines_overlapping_same_side_sources():
  merged = merge_zones([
    Zone(
      100,
      104,
      "demand",
      origin_index=2,
      source="order_block",
      break_kind="BOS",
      break_index=4,
    ),
    Zone(102, 105, "demand", origin_index=3, source="bullish_fvg"),
    Zone(110, 112, "supply", origin_index=1, source="supply_demand"),
  ])

  demand = [zone for zone in merged if zone.side == "demand"]
  assert len(demand) == 1
  assert demand[0].low == 100
  assert demand[0].high == 105
  assert demand[0].sources == ["order_block", "bullish_fvg"]
  assert demand[0].source == "order_block"
  assert demand[0].break_kind == "BOS"
  assert [zone.side for zone in merged].count("supply") == 1


def test_score_zones_prefers_fresh_ob_round_level_liquidity_and_htf():
  strong = Zone(
    4099,
    4101,
    "demand",
    source="order_block",
    break_kind="BOS",
    touches=0,
  )
  weak = Zone(4104, 4105, "demand", source="bullish_fvg", touches=2)
  htf = Zone(4098, 4102, "demand", source="supply_demand")

  scored = score_zones(
    [weak, strong],
    [Level(4100, "reaction", touches=3, band=1.0)],
    [Pool("sell", 4098.8, 0.2, touches=2)],
    round_step=5,
    htf_zones=[htf],
  )

  assert scored[0].low == 4099
  assert scored[0].score > scored[1].score
  assert scored[0].score >= 13
  assert {"fresh", "OB", "key level", "round 4100", "liquidity pool", "HTF zone"} <= set(
    scored[0].score_reasons
  )


def _tf_item(
  zones: list[Zone],
  *,
  structure: str = "range",
  momentum_value: str = "neutral",
) -> TimeframeAnalysis:
  df = _df([(100, 101, 99, 100)])
  return TimeframeAnalysis(
    df=df,
    atr=pd.Series([1.0], index=df.index),
    swings=[],
    structure=structure,
    breaks=[],
    key_levels=[],
    legs=[],
    supply_demand_zones=[],
    order_blocks=[zone for zone in zones if "order_block" in zone.sources],
    flip_zones=[],
    fvg_zones=[],
    zones=zones,
    liquidity_pools=[],
    liquidity_grabs=[],
    momentum=momentum_value,
  )


def test_mtf_second_pass_adds_htf_zone_score_to_lower_tf():
  lower = Zone(
    100,
    101,
    "demand",
    source="order_block",
    break_kind="BOS",
  )
  higher = Zone(99, 102, "demand", source="supply_demand")

  updated = _apply_mtf_zone_scores(
    {
      "M5": _tf_item([lower]),
      "M30": _tf_item([higher]),
    },
    AnalysisSettings(round_step=0),
  )

  scored = updated["M5"].zones[0]
  assert scored.score == 9
  assert "HTF zone" in scored.score_reasons
  assert updated["M5"].order_blocks == [scored]


def test_htf_bias_fallback_is_deterministic_by_timeframe_rank():
  low_tf = _tf_item([], structure="up", momentum_value="bull")
  high_tf = _tf_item([], structure="down", momentum_value="bear")

  assert _htf_bias({"M5": low_tf, "M30": high_tf}, []) == "down"
  assert _htf_bias({"M30": high_tf, "M5": low_tf}, []) == "down"


def test_key_levels_cluster_repeated_swings_and_drop_lone_touch():
  swings = [
    Swing(1, "high", 100.0),
    Swing(3, "high", 100.4),
    Swing(5, "high", 100.8),
    Swing(7, "low", 110.0),
  ]

  levels = key_levels(swings, atr=2.0, level_cluster_atr=0.5, min_touches=2)

  assert len(levels) == 1
  assert levels[0].touches == 3
  assert 100.0 <= levels[0].price <= 100.8


def test_liquidity_pool_and_grab_from_equal_highs():
  df = _df([
    (99, 100, 98, 99),
    (99, 100.1, 98, 99.5),
    (99.5, 100.4, 98, 99.8),
  ])
  swings = [
    Swing(0, "high", 100.0),
    Swing(1, "high", 100.05),
  ]

  pools = liquidity_pools(swings, df, equal_tol_atr=0.2, atr=pd.Series([1, 1, 1]))
  grabs = liquidity_grabs(df, pools)

  assert any(pool.side == "buy" and pool.touches == 2 for pool in pools)
  assert any(grab.direction == "bear" for grab in grabs)


def test_price_only_momentum_bull_and_neutral():
  bull = _df([
    (100, 103, 99.8, 102.8),
    (102.8, 106, 102.5, 105.8),
    (105.8, 109, 105.5, 108.8),
    (108.8, 112, 108.5, 111.8),
  ])
  choppy = _df([
    (100, 102, 98, 100.2),
    (100.2, 102, 98, 99.9),
    (99.9, 102, 98, 100.1),
    (100.1, 102, 98, 100.0),
  ])

  assert momentum(bull, pd.Series([1, 2, 3, 4]), lookback=4) == "bull"
  assert momentum(choppy, pd.Series([1, 1, 1, 1]), lookback=4) == "neutral"


def test_analyze_assembles_per_tf_outputs_and_htf_bias():
  m5 = _df([
    (100, 101, 99, 100),
    (100, 105, 100, 104),
    (104, 104.5, 98, 99),
    (99, 108, 99, 107),
    (107, 107.5, 101, 102),
    (102, 111, 102, 110),
    (110, 110.5, 104, 105),
  ])
  m15 = _df([
    (100, 103, 99.8, 102.8),
    (102.8, 106, 102.5, 105.8),
    (105.8, 109, 105.5, 108.8),
    (108.8, 112, 108.5, 111.8),
  ])

  ctx = analyze(
    {"M5": m5, "M15": m15},
    AnalysisSettings(zigzag_atr_mult=0.0, key_level_min_touches=1),
    ["M15"],
  )

  assert set(ctx.per_tf) == {"M5", "M15"}
  assert ctx.htf_bias in {"up", "down", "range"}
  assert all(hasattr(zone, "mitigated") for item in ctx.per_tf.values() for zone in item.zones)


def test_analysis_modules_have_no_delivery_or_state_imports():
  import app.analysis as analysis
  import app.levels as levels
  import app.liquidity as liquidity
  import app.momentum as momentum_module
  import app.pa_math as pa_math
  import app.pa_types as pa_types
  import app.structure as structure
  import app.swings as swings_module
  import app.zones as zones

  forbidden = {
    "redis_state",
    "send_with_retry",
    "broadcast_entry",
    "store_manual_signal",
  }
  modules = [
    analysis,
    levels,
    liquidity,
    momentum_module,
    pa_math,
    pa_types,
    structure,
    swings_module,
    zones,
  ]

  for module in modules:
    assert forbidden.isdisjoint(vars(module))
