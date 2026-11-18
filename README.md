# Dip-reversion bot — btc-race-24h-20261118-1444

Buys a deep dip below the 2-hour average once the 5-minute slide has eased,
exits on the first bounce. Long only, full size, one open position.

## Rules

- **Entry** (flat only): close ≥ 70 bps below the 120-bar SMA **and**
  5-bar return ≥ −20 bps; 60-bar cooldown after every exit.
- **Exit** (holding): take profit +80 bps vs entry close, trailing stop
  90 bps below the peak close since entry, hard stop −80 bps vs entry.
- Orders: `max_slippage_bps` 150, min notional respected, at most 1 order/reply.

## Why

The dev window is a choppy, alternating grind (BTC −280 bps over the day,
1-min return sd 6.7 bps, no sustained trend). Momentum legs lose money on
it; a plain trailing stop whipsaws. The dip + easing-confirmation rule was
the only family positive on **both** the dev window and the previous day's
window (pseudo out-of-sample), and neighbouring parameters stay positive
— it is a plateau, not a tuned spike. TP 90/100 bps improves the dev
window but turns the prior window negative, so it was rejected.

## Verified numbers (exact-integer simulator, validated vs official grade)

| Window | Net PnL | Trades | Max DD | Fees |
|---|---|---|---|---|
| Dev (2026-11-18) | **+$10.46** | 4 | 0.76% | $1.61 |
| Prior day (pseudo-OOS) | **+$1.58** | 3 | 1.00% | $1.61 |

Buy-and-hold on the dev window: ≈ −$28. Dev gate: net PnL > 0 — passed.

## Files

- `main.py` — the bot (Python 3.13 stdlib only, protocol agent-fun/bars-replay/v1)
- `vendor/makefun_bars.py` — kit SDK shim, byte-for-byte copy
- `tests/test_strategy.py` — 10 unit tests (entry, exits, cooldown, determinism)
- `LICENSE` — MIT (via `makefun init`)
