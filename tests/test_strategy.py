"""Tests for the dip-reversion bot (test_driven_development: red first).

Strategy under test (see main.py):
  entry: close >= 70 bps below the 120-bar SMA AND 5-bar return >= -20 bps
         (dip + selling-easing confirmation), flat only, 60-bar cooldown
  exit:  TP +80 bps vs entry close / trailing stop 90 bps below peak close /
         hard stop -80 bps vs entry close.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import Bot, ret_bps  # noqa: E402

BASE = 6_500_000_000


def enter_bot():
    """Feed a bot 120 flat bars, a 5-bar slide to -100 bps, then 11 flat
    bars at the dip level; the buy fires once the 5-bar return has eased
    to 0. Returns (bot, entry_close)."""
    bot = Bot()
    closes = [BASE] * 120
    closes += [BASE * 9990 // 10000, BASE * 9980 // 10000, BASE * 9970 // 10000,
               BASE * 9960 // 10000, BASE * 9950 // 10000]
    closes += [BASE * 9900 // 10000] * 11
    order = None
    for c in closes:
        order = bot.decide(c, 1_000_000_000, 0)
    assert order is not None and order["side"] == "buy", "setup: buy never fired"
    assert order["notional_quote_units"] == 1_000_000_000
    return bot, closes[-1]


def test_ret_bps_integer():
    assert ret_bps(10100, 10000) == 100
    assert ret_bps(9900, 10000) == -100
    assert ret_bps(10000, 10000) == 0


def test_no_trade_before_sma_ready():
    bot = Bot()
    for c in [BASE] * 50:
        assert bot.decide(c, 1_000_000_000, 0) is None


def test_no_buy_without_dip():
    bot = Bot()
    for c in [BASE] * 130:
        assert bot.decide(c, 1_000_000_000, 0) is None


def test_buy_on_dip_with_confirmation():
    bot, entry = enter_bot()
    assert entry == BASE * 9900 // 10000


def test_no_buy_while_still_falling():
    bot = Bot()
    closes = [BASE] * 120
    # steady -20 bps/bar slide: deep dip but 5-bar return -100 bps -> no entry
    for k in range(1, 11):
        closes.append(BASE * (10000 - 20 * k) // 10000)
    order = None
    for c in closes:
        order = bot.decide(c, 1_000_000_000, 0)
    assert order is None


def test_take_profit_at_plus_80():
    bot, entry = enter_bot()
    qty = 15_000_000  # ~1 BTC at 65k (qty scale 8)
    # rise to +79 bps: no sell; +80 bps: sell
    assert bot.decide(entry * 10079 // 10000, 0, qty) is None
    sell = bot.decide(entry * 10080 // 10000, 0, qty)
    assert sell is not None and sell["side"] == "sell" and sell["qty"] == qty


def test_trailing_stop_90_below_peak():
    bot, entry = enter_bot()
    qty = 15_000_000
    assert bot.decide(entry * 10050 // 10000, 0, qty) is None  # peak +50
    assert bot.decide(entry * 9990 // 10000, 0, qty) is None   # ~-60 from peak
    sell = bot.decide(entry * 9955 // 10000, 0, qty)           # ~-95 from peak
    assert sell is not None and sell["side"] == "sell"


def test_hard_stop_minus_80():
    bot, entry = enter_bot()
    qty = 15_000_000
    assert bot.decide(entry * 9921 // 10000, 0, qty) is None  # -79
    sell = bot.decide(entry * 9920 // 10000, 0, qty)          # -80
    assert sell is not None and sell["side"] == "sell"


def test_cooldown_blocks_reentry_60_bars():
    bot, entry = enter_bot()
    qty = 15_000_000
    bot.decide(entry * 10080 // 10000, 0, qty)  # TP sell; cooldown starts
    dip = BASE * 9900 // 10000
    # dip again immediately: still cooling down
    for _ in range(59):
        assert bot.decide(dip, 1_000_000_000, 0) is None
    # a fresh, deeper slide to -200 bps below the old dip level, then flat:
    # the buy may only fire once the 60-bar cooldown has expired AND the
    # 5-bar return has eased (the SMA has meanwhile drifted down, so the
    # old dip level alone is no longer deep enough).
    lower = BASE * 9700 // 10000
    slide = [dip * (10000 - 20 * k) // 10000 for k in range(1, 6)]
    got = None
    for c in slide + [lower] * 11:
        got = bot.decide(c, 1_000_000_000, 0)
    assert got is not None and got["side"] == "buy"


def test_deterministic_same_orders():
    # A sequence that really buys and then sells: compare the full order
    # lists (not just "do nothing") across two fresh bots.
    base = BASE
    seq = [base] * 120
    seq += [base * 9990 // 10000, base * 9980 // 10000, base * 9970 // 10000,
            base * 9960 // 10000, base * 9950 // 10000]
    seq += [base * 9900 // 10000] * 11
    outs = []
    for _ in range(2):
        bot = Bot()
        got = []
        for c in seq:
            got.append(bot.decide(c, 1_000_000_000, 0))
        entry = seq[-1]
        got.append(bot.decide(entry * 10080 // 10000, 0, 15_000_000))
        outs.append(got)
    assert outs[0] == outs[1]
    assert any(o is not None and o["side"] == "buy" for o in outs[0])
    assert any(o is not None and o["side"] == "sell" for o in outs[0])


# ---- protocol layer: on_batch through the real shim -----------------------

def _hello(warmup_bars=0):
    import main as _m
    import makefun_bars as _sdk  # noqa: F401  (imported after main sets sys.path)
    return {
        "type": "hello", "protocol": "agent-fun/bars-replay/v1", "seed": "7",
        "symbols": [{"symbol": "CBBTC",
                     "mint": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",
                     "price_scale": 5, "qty_scale": 8}],
        "capital": {"quote": "USDC", "quote_scale": 6, "quote_units": "1000000000"},
        "bar_interval": "1m", "first_close_ms": 1_767_229_200_000,
        "caps": {"max_open_positions": 1, "max_orders_per_bar": 16,
                 "max_weight_bps": 10000, "shorts": False, "leverage": False},
        "fees": {"fee_bps": 4, "slippage_bps": 2,
                 "min_notional_quote_units": "1000000"},
        "latency_bars": 1, "warmup_bars": warmup_bars,
    }


def _batch(seq, close, cash=1_000_000_000, qty=0, symbol="CBBTC"):
    import makefun_bars as sdk  # noqa: F401
    bar = {"symbol": symbol, "t": 1_767_229_200_000 + seq * 60_000,
           "o": str(close), "h": str(close), "l": str(close), "c": str(close),
           "v": None, "o_depth": ["1000000000000"], "c_depth": ["1000000000000"]}
    acct = {"cash_quote_units": str(cash),
            "positions": ([{"symbol": "CBBTC", "qty": str(qty),
                            "cost_quote_units": "1000000000"}] if qty else []),
            "equity_quote_units": str(cash)}
    return {"type": "batch", "seq": seq, "t": 1_767_229_200_000 + seq * 60_000,
            "bars": [bar], "fills": [], "account": acct}


def test_on_batch_warmup_records_history_but_orders_nothing():
    import main as m
    import makefun_bars as sdk
    m.BOT = Bot()
    state = sdk.BarsState(_hello(warmup_bars=120))
    for seq in range(120):
        state.apply_batch(_batch(seq, BASE))
        assert m.on_batch(state, _batch(seq, BASE)) == []
    assert len(m.BOT.closes) == 120
    # the same dip shape that buys with no warm-up must buy now too
    # (stop at the first buy: the test harness reports qty 0, so a bot
    # that stayed flat would keep re-buying every bar)
    orders = []
    for k, c in enumerate([BASE * 9990 // 10000, BASE * 9980 // 10000,
                           BASE * 9970 // 10000, BASE * 9960 // 10000,
                           BASE * 9950 // 10000] + [BASE * 9900 // 10000] * 11):
        seq = 120 + k
        state.apply_batch(_batch(seq, c))
        orders.extend(m.on_batch(state, _batch(seq, c)))
        if orders:
            break
    assert len(orders) == 1 and orders[0]["side"] == "buy"
    state.to_orders(orders)  # wire-shape validation by the shim


def test_on_batch_no_cbbtc_bar_returns_nothing():
    import main as m
    import makefun_bars as sdk
    m.BOT = Bot()
    state = sdk.BarsState(_hello())
    empty = {"type": "batch", "seq": 0, "t": 1_767_229_200_000, "bars": [],
             "fills": [], "account": {"cash_quote_units": "1000000000",
                                      "positions": [], "equity_quote_units": "1000000000"}}
    state.apply_batch(empty)
    assert m.on_batch(state, empty) == []
    other = _batch(1, BASE, symbol="OTHER")
    state.apply_batch(other)
    assert m.on_batch(state, other) == []
