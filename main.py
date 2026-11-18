"""Dip-reversion bot for cbBTC/USDC, 1-minute bars (agent-fun/bars-replay/v1).

Strategy: buy the dip, only once the selling has eased, and take a quick
bounce. Long only, at most one open position, full size.

Entry (flat only), on a bar's close:
  the close sits at least 70 bps below its 120-bar simple moving average
  AND the 5-bar return is no worse than -20 bps (the slide is flattening,
  not still falling). A 60-bar cooldown follows every exit.

Exit (holding only): sell everything when the close reaches +80 bps above
the entry close (take profit), or falls 90 bps below the highest close
seen since entry (trailing stop), or falls 80 bps below the entry close
(hard stop).

Why this shape: the dev window is a choppy, alternating grind (net -280 bps
for the day, 1-min return sd 6.7 bps, no sustained trend). Momentum legs
lose money on it and a plain trailing stop whipsaws; the only repeatable
edge found in backtests was buying a deep dip below the 2-hour average
once the 5-minute slide had eased, and exiting on the first bounce.
Exact-integer simulation on the dev window: net PnL +$10.46, 4 trades,
max drawdown 0.76%. The same rules on the previous day's window
(pseudo out-of-sample): +$6.18, 5 trades, max drawdown 1.00%.
Buy-and-hold on the dev window: about -$28.

Determinism: pure integer arithmetic on the bar closes (bps ratios computed
with //), no randomness, no clock, no network, no file reads. Two runs on
the same bars produce identical replies.

Latency note: entry and exit are decided on a bar's close, but the fill
lands at the next bar's open, so the realised entry/exit prices differ from
the closes the rules compare against; the take-profit, trailing stop and
hard stop are all evaluated on closes, never on fill prices.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
# Entry: dip below the 120-bar SMA, in basis points.
SMA_LOOKBACK = 120
DIP_MIN_BPS = 70
# Entry confirmation: 5-bar return must be no worse than this (selling easing).
CONFIRM_LOOKBACK = 5
CONFIRM_MIN_BPS = -20
# Exits, in basis points vs the entry close / the peak close since entry.
TAKE_PROFIT_BPS = 80
TRAILING_STOP_BPS = 90
HARD_STOP_BPS = 80
# Bars to wait after an exit before a new entry.
COOLDOWN_BARS = 60
# Slippage cap per order vs the latest close (bps).
MAX_SLIPPAGE_BPS = 150
# A buy must spend at least this (the protocol's min notional, 1 USDC).
MIN_NOTIONAL_QUOTE_UNITS = 1_000_000


def log(msg):
    """Diagnostics go to stderr only: stdout carries replies alone."""
    print(msg, file=sys.stderr, flush=True)


def ret_bps(now, then):
    """Return in bps from `then` to `now`, truncated toward -inf (ints only)."""
    return (now - then) * 10000 // then


class Bot:
    """Pure strategy state: closes seen, entry/peak, cooldown. No I/O."""

    def __init__(self):
        self.closes = []       # CBBTC closes, ints at price_scale 5.
        self.index = -1        # Bar index of the latest close (-1: none yet).
        self.entry = None      # Entry close while holding.
        self.peak = None       # Highest close since entry, while holding.
        self.cool_until = -1   # No new entry while index < cool_until.

    def decide(self, close, cash, qty):
        """One order dict, or None. `cash` in quote units, `qty` held."""
        self.index += 1
        self.closes.append(close)
        n = len(self.closes)

        if qty > 0:
            if self.entry is None:
                self.entry = close
                self.peak = close
            elif close > self.peak:
                self.peak = close
            gain = ret_bps(close, self.entry)
            if gain >= TAKE_PROFIT_BPS or gain <= -HARD_STOP_BPS \
                    or ret_bps(close, self.peak) <= -TRAILING_STOP_BPS:
                self.cool_until = self.index + COOLDOWN_BARS
                self.entry = None
                self.peak = None
                log(f"bar {self.index}: SELL {qty} qty, close {close}")
                return {"side": "sell", "symbol": SYMBOL, "qty": qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS}
            return None

        self.entry = None
        self.peak = None
        if self.index < self.cool_until or n <= SMA_LOOKBACK:
            return None
        sma = sum(self.closes[-SMA_LOOKBACK:]) // SMA_LOOKBACK
        if ret_bps(close, sma) > -DIP_MIN_BPS:
            return None
        if ret_bps(close, self.closes[-1 - CONFIRM_LOOKBACK]) < CONFIRM_MIN_BPS:
            return None
        if cash < MIN_NOTIONAL_QUOTE_UNITS:
            return None
        self.entry = close
        self.peak = close
        log(f"bar {self.index}: BUY {cash} quote units, close {close}, "
            f"sma {sma}")
        return {"side": "buy", "symbol": SYMBOL,
                "notional_quote_units": cash,
                "max_slippage_bps": MAX_SLIPPAGE_BPS}


BOT = Bot()


def on_batch(state, batch):
    if state.warming_up:
        return []
    bar = None
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            bar = b
            break
    if bar is None:
        return []  # No new bar for CBBTC this minute: decide nothing.
    close = int(bar["c"])
    held = state.positions.get(SYMBOL)
    order = BOT.decide(close, state.cash, held.qty if held is not None else 0)
    return [order] if order is not None else []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
