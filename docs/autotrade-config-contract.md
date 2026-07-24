# Auto-trade configuration contract

The Python publisher and C# executor share config manifest version 2 and
candidate contract version 5. Cross-service values use these canonical
environment variables:

```text
AUTO_TRADE_PROFILE
AUTO_TRADE_ENABLED
AUTO_TRADE_DRY_RUN
AUTO_TRADE_CANDIDATE_STREAM
AUTO_TRADE_EVENT_STREAM
AUTO_TRADE_CANDIDATE_CONTRACT_VERSION
AUTO_TRADE_SYMBOLS
AUTO_TRADE_CANONICAL_SYMBOL
AUTO_TRADE_XAU_PIP_SIZE
AUTO_TRADE_XAU_CONTRACT_SIZE
AUTO_TRADE_TARGET_PLANS_PIPS
AUTO_TRADE_RANGE_TARGETS_PIPS
AUTO_TRADE_RANGE_TP_BUFFER_PIPS
AUTO_TRADE_CANDIDATE_MAX_AGE_SECONDS
AUTO_TRADE_CANDIDATE_STORAGE_TTL_SECONDS
AUTO_TRADE_SPOT_MAX_AGE_SECONDS
AUTO_TRADE_RANGE_FLIP_ENABLED
AUTO_TRADE_RANGE_TWO_SIDED_ENABLED
AUTO_TRADE_ALLOW_CONCURRENT_STRATEGIES
AUTO_TRADE_ALLOW_COUNTER_BIAS
AUTO_TRADE_ZONE_FILL_ENABLED
AUTO_TRADE_MIN_CONFLUENCE
AUTO_TRADE_REQUIRE_DEMO_ACCOUNT
AUTO_TRADE_NON_HEDGED_OPPOSITE_POLICY
```

Canonical manifest representation:

- Symbols are uppercase, unique, and ascending.
- Target plans are integer pips, unique, and ascending.
- Brokers `fpmarkets`, `fpmarkets-sc`, and `fpmarketssc` normalize to
  `fpmarkets`.
- Account aliases normalize to `demo` or `live`; the demo requirement is a
  separate boolean.
- Numeric JSON values compare by value, so `3` and `3.0` are equivalent.

Runtime target selection is intentionally separate. Range targets are sorted
descending before selection so the largest target that fits is selected.

`AUTO_TRADE_CANDIDATE_MAX_AGE_SECONDS` controls order eligibility.
`AUTO_TRADE_CANDIDATE_STORAGE_TTL_SECONDS` controls Redis audit retention.
The former is fatal when services disagree; the latter is warning-only.

For non-hedged accounts,
`AUTO_TRADE_NON_HEDGED_OPPOSITE_POLICY` must be one of:

- `broker_netting`
- `close_then_reverse`
- `reject`

Non-hedged capability is visible as a warning and does not itself disable a
demo executor.
