# Demo evaluation auto-trade

`AUTO_TRADE_PROFILE=demo_eval` maximizes valid structure-based execution on a
broker-confirmed demo account. It does not relax quote freshness, order
geometry, ownership, idempotency, stop, or target validation. A live account
is fatal and no order is submitted.

## Required environment

```dotenv
AUTO_TRADE_PROFILE=demo_eval
AUTO_TRADE_ENABLED=true
AUTO_TRADE_DRY_RUN=false
AUTO_TRADE_REQUIRE_DEMO_ACCOUNT=true
AUTO_TRADE_EXPECTED_BROKER=fpmarkets
AUTO_TRADE_ALLOW_CONCURRENT_STRATEGIES=true
AUTO_TRADE_ALLOW_HEDGED_XAU=true
AUTO_TRADE_REQUIRE_FLAT_FOR_RANGE=false
AUTO_TRADE_TREND_ENABLED=true
AUTO_TRADE_RANGE_ENABLED=true
AUTO_TRADE_RANGE_TWO_SIDED_ENABLED=true
AUTO_TRADE_RANGE_FLIP_ENABLED=true
AUTO_TRADE_MAPPED_ZONE_ENABLED=true
AUTO_TRADE_STRATEGY_MATCH_ENABLED=true
AUTO_TRADE_BREAKOUT_ENABLED=true
AUTO_TRADE_RETEST_ENABLED=true
AUTO_TRADE_REACTION_ENABLED=true
AUTO_TRADE_LIQUIDITY_REVERSAL_ENABLED=true
AUTO_TRADE_MULTI_MATCH_ENABLED=true
AUTO_TRADE_ALLOW_COUNTER_BIAS=true
AUTO_TRADE_TRACK_ALL_STRUCTURAL_MATCHES=true
AUTO_TRADE_CANDIDATE_CONTRACT_VERSION=4
AUTO_TRADE_CANONICAL_SYMBOL=XAU
MANUAL_ALGO_ENABLED=true
MANUAL_ALGO_DRY_RUN=false
SCANNER_TOP_N=0
AUTO_TRADE_MAX_TRACKED_CANDIDATES=0
AUTO_TRADE_MAX_ACTIVE_POSITIONS_PER_SYMBOL=0
```

Explicit environment values win over profile defaults, except
`AUTO_TRADE_REQUIRE_DEMO_ACCOUNT=false`, which is invalid for `demo_eval`.
`AUTO_TRADE_EXPECTED_BROKER=fpmarkets` accepts the broker-reported
`FP Markets` spelling after normalized identity comparison.

Owner `/algo` candidates bypass autonomous strategy selection and keep the
entered SL/TP prices unchanged. Telegram first reports `ALGO REQUEST RECEIVED`
and waits for the C# executor event before claiming a limit order, fill,
dry-run or rejection.

## Deploy

Run tests before building or restarting the demo services:

```bash
cd /opt/apexvoid-trading-bot
docker compose build bot ctrader-engine
docker compose up -d --no-deps bot ctrader-engine
docker compose ps bot ctrader-engine
docker compose logs --since=10m bot ctrader-engine
```

Expected startup output reports `profile=demo_eval`, a demo account, account
hedging capability, the resolved exposure policy, and config health. A
broker-confirmed live account reports `config_fatal` and terminates the
executor.

## Redis verification

```bash
docker compose exec redis redis-cli GET auto_trade:config_manifest:python
docker compose exec redis redis-cli GET auto_trade:config_manifest:ctrader
docker compose exec redis redis-cli GET auto_trade:config_health
docker compose exec redis redis-cli GET auto_trade:executor_snapshot:XAU
docker compose exec redis redis-cli GET auto_trade:range_context:XAU
docker compose exec redis redis-cli GET auto_trade:range_context_compare:XAU
docker compose exec redis redis-cli GET auto_trade:strategy_matches:XAU
docker compose exec redis redis-cli HGETALL auto_trade:metrics:XAU
docker compose exec redis redis-cli --scan --pattern 'auto_trade:evaluation:XAU:*'
docker compose exec redis redis-cli XREVRANGE auto_trade:lifecycle_events + - COUNT 20
docker compose exec redis redis-cli XREVRANGE auto_trade:events + - COUNT 20
```

For the current resolved `range_id`, inspect both rails:

```bash
docker compose exec redis redis-cli --scan --pattern 'auto_trade:range_side:XAU:*'
```

The evaluation evidence is:

- `config_health.state` is `healthy`.
- Python and executor manifests agree on enabled state, dry-run state, manual
  state, candidate/event streams, Redis DB, symbol, pip size and target plans.
- The executor snapshot reports `demo=true`, `hedged=true`, and `ready=true`.
- Both BUY and SELL range-side keys coexist.
- `strategy_matches:XAU` contains distinct active theses.
- Lifecycle history reaches `order_filled` and `managing` for BUY and SELL.
- Executor metrics include Range Box execution with existing/opposite exposure.
- Position snapshots retain distinct candidate and group IDs after restart.
- Counter-bias candidates retain `bias` and `relationship_to_bias` metadata
  without being demoted to analysis-only.

## Rollback

Stop autonomous order intake first, then rebuild:

```bash
sed -i 's/^AUTO_TRADE_ENABLED=.*/AUTO_TRADE_ENABLED=false/' .env
docker compose up -d --build --no-deps bot ctrader-engine
```

Switching to `AUTO_TRADE_PROFILE=conservative` restores the prior flat exposure
policy defaults. Existing broker positions remain owned and reconciled; the
profile change does not close them automatically.
