# Algo Market Map + Forming Gate

## Objective

Let ApexVoid Algo execute a scanner `Range Edge Scalp` without parsing a
Telegram card and without letting scanner output bypass execution safety.

The scanner owns range discovery. The Algo worker owns entry timing, order
safety, idempotency, re-arming, and box retirement.

## Data flow

```text
closed M5 bar
  -> scanner PA analysis
  -> validated two-sided Market Map rails
  -> Range Edge Scalp forming result overlaps the matching rail
  -> versioned FormingRangeSetup in Redis (short TTL)
  -> next closed M1 bars
  -> recent rejection at the nominated rail
  -> drift / room / structure / news / exposure / spread gates
  -> auto_trade:candidates
```

No rendered message is an input. Telegram delivery may be disabled, fail, or
be duplicate-suppressed without changing the typed gate contract.

## Scanner admission

The scanner emits an intent only when all of these are true:

1. The selected digest contains `Range Edge Scalp` in `range_scalp` mode.
2. Market Map exposes one validated `BUY` rail and one validated `SELL` rail.
3. The forming entry zone overlaps the rail for its direction.
4. Both rails form an ordered range (`BUY < SELL`).

An M5 scan that no longer meets the contract deletes the active intent. The
Redis TTL is a second stale-data boundary.

## Algo admission

While a fresh mapped intent exists it is authoritative for the range family:

- The private 60-bar M1 box is not traded while the mapped intent is active.
- Trend/breakout publishing is suppressed so two strategy families cannot
  publish contradictory candidates from one M1 close.
- The scanner's range classification is not vetoed by a second, conflicting
  private regime label.

The mapped intent still requires:

1. Fresh M1/M5 history and a finite ATR.
2. No accepted break outside the mapped box.
3. A recent M5 touch whose close still holds/reclaims the nominated rail.
4. A matching M1 rejection in the configured recent-bar window.
5. Live price no farther than 10 pips from the nominated rail.
6. Enough room for a full +50 or +70-pip target toward the opposite rail.
7. Existing EQ, edge-proximity, HTF-zone, news, structure-stop, RR, spread,
   quote-freshness, paused-state, and flat-exposure guards.

The candidate keeps the executor's `Range Box Scalp`/`auto_box_scalp`
contract and adds `signal_source=market_map_forming` for attribution.

## Identity and state

- `setup_id` identifies one direction on one scanner event.
- `range_id` is bucketed from the two map rails and is shared by BUY and SELL
  cards for the same box.
- A used edge is disarmed until price closes through box EQ.
- A confirmed break retires the shared `range_id`, including a later card from
  the opposite side.

## Redis contract

```text
SETEX auto_trade:forming_gate:{SYMBOL} <ttl> <FormingRangeSetup JSON>
```

The payload is versioned and contains source timestamps, expiry, direction,
entry/key level, confluence, both raw Market Map rail bands, map bias, and
human-readable reasons. Invalid versions, malformed values, symbol mismatch,
and expired payloads fail closed and are removed.

## Controls and telemetry

```text
AUTO_TRADE_FORMING_GATE_ENABLED=false
AUTO_TRADE_FORMING_MAX_AGE_SECONDS=420
AUTO_TRADE_FORMING_M1_CONFIRMATION_BARS=5
AUTO_TRADE_FORMING_M5_STRUCTURE_BARS=3
```

The bridge is disabled by default. `/auto_status` reports either `private M1
two-edge box` or `Market Map + forming + M1`; `auto_trade:last_gate*` includes
`gate_source`, typed scanner M5 confirmation, direct M5 structure state, and
the active forming metadata.
