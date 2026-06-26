# ui/conviction_table.py
# Shared styling for the Conviction-Radar behind-the-scenes table, so the intraday
# page (18) and the positional 2H page (19) render identically without duplicating
# ~200 lines of colour logic. style_candle_table(ct) → a pandas Styler; column_key_md()
# → the legend markdown.

import pandas as pd

_GREEN, _RED, _AMBER, _BLUE = (22, 163, 74), (220, 38, 38), (245, 158, 11), (14, 165, 233)
_STATE_TXT = {"BOUNCE_BREWING": "#16a34a", "UPTREND": "#0ea5e9",
              "DOWNTREND": "#dc2626", "TOPPING": "#d97706", "NEUTRAL": "#94a3b8"}


def _bg(base, f):
    """Background blend white→base as f goes 0→1, with readable text."""
    f = max(0.0, min(1.0, f))
    r, g, b = base
    rr, gg, bb = (int(255 + (c - 255) * f) for c in (r, g, b))
    txt = "#ffffff" if f > 0.55 else "#0f172a"
    return f"background-color:rgb({rr},{gg},{bb});color:{txt};font-weight:600;"


def _heat(val, base):
    try:
        f = max(0.0, min(1.0, float(val) / 100.0))
    except (TypeError, ValueError):
        return ""
    if f <= 0:
        return "color:#94a3b8;"
    return _bg(base, f)


def _net_css(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    f = min(1.0, abs(n) / 100.0)
    if f < 0.05:
        return "color:#94a3b8;"
    r, g, b = (22, 163, 74) if n > 0 else (220, 38, 38)
    rr, gg, bb = (int(255 + (c - 255) * f) for c in (r, g, b))
    txt = "#ffffff" if f > 0.55 else "#0f172a"
    return f"background-color:rgb({rr},{gg},{bb});color:{txt};font-weight:700;"


def _delta_css(v):
    try:
        return "color:#16a34a;font-weight:600;" if float(v) > 0 else \
               "color:#dc2626;font-weight:600;" if float(v) < 0 else ""
    except (TypeError, ValueError):
        return ""


def _stretch_css(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    f = min(1.0, abs(x) / 2.0)
    if f < 0.05:
        return "color:#94a3b8;"
    return _bg(_GREEN if x > 0 else _RED, f)


def _brd_css(v):
    try:
        b = float(v)
    except (TypeError, ValueError):
        return ""
    if 45 <= b <= 55:
        return "color:#94a3b8;"
    if b > 55:
        return _bg(_GREEN, (b - 55) / 45.0)
    return _bg(_RED, (45 - b) / 45.0)


def _clv_css(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if abs(x) < 0.05:
        return "color:#94a3b8;"
    return _bg(_GREEN if x > 0 else _RED, abs(x))


def _vote_css(v):
    s = str(v)
    if "▲" in s or "↑" in s:
        return "color:#16a34a;font-weight:700;"
    if "▼" in s or "↓" in s:
        return "color:#dc2626;font-weight:700;"
    return "color:#cbd5e1;"


def _state_css(v):
    return f"color:{_STATE_TXT.get(v, '#0f172a')};font-weight:700;"


def _hilo_css(v):
    s = str(v).replace(" ", "")
    up, dn = s.count("▲"), s.count("▼")
    if up == 2:
        return _bg(_GREEN, 0.6) + "text-align:center;"
    if dn == 2:
        return _bg(_RED, 0.6) + "text-align:center;"
    if s == "▲▼":
        return _bg(_AMBER, 0.45) + "text-align:center;"
    base = ("color:#475569;font-weight:700;" if (up and dn)
            else "color:#16a34a;font-weight:700;" if up
            else "color:#dc2626;font-weight:700;" if dn
            else "color:#cbd5e1;")
    return base + "text-align:center;"


def _rsi_css(v, falling=False):
    try:
        r = float(v)
    except (TypeError, ValueError):
        return ""
    if r >= 70:      bg, fg = "#fb923c", "#3a1500"
    elif r >= 55:    bg, fg = "#86efac", "#064e3b"
    elif r >= 45:    bg, fg = "#e2e8f0", "#334155"
    elif r >= 30:    bg, fg = "#fca5a5", "#7f1d1d"
    else:            bg, fg = "#c4b5fd", "#3b0764"
    if falling:
        fg = "#dc2626"
    return f"background-color:{bg};color:{fg};font-weight:{'800' if falling else '600'};"


def _pctb_state_css(v, new_hi, new_lo, hold_up, hold_dn):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 1.0:
        return _bg(_GREEN, 0.9) if new_hi else _bg(_AMBER, 0.7)
    if x > 0.55:
        if new_hi:
            return _bg(_GREEN, 0.45 + (x - 0.55) / 0.45 * 0.55)
        return _bg(_GREEN, 0.16) if hold_up else "color:#94a3b8;"
    if x < 0.0:
        return _bg(_RED, 0.9) if new_lo else _bg(_AMBER, 0.7)
    if x < 0.45:
        if new_lo:
            return _bg(_RED, 0.45 + (0.45 - x) / 0.45 * 0.55)
        return _bg(_RED, 0.16) if hold_dn else "color:#94a3b8;"
    return "color:#94a3b8;"


def style_candle_table(ct: pd.DataFrame):
    """Return a styled pandas Styler for a candle_table() DataFrame (newest-first)."""
    def _m(s, func, *names):
        cols = [n for n in names if n in ct.columns]
        return s.map(func, subset=cols) if cols else s

    def _wick_row(row):
        out = pd.Series("", index=row.index)
        try:
            o, h, l, c = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
        except (TypeError, ValueError, KeyError):
            return out
        rng = h - l
        if rng <= 0:
            return out
        lw, uw = (min(o, c) - l) / rng, (h - max(o, c)) / rng
        body = abs(c - o) / rng
        if "LWick" in row.index:
            f = lw if lw >= 0.25 else (body if (c > o and lw < 0.15) else 0.0)
            out["LWick"] = _bg(_GREEN, f) if f >= 0.1 else "color:#94a3b8;"
        if "UWick" in row.index:
            f = uw if uw >= 0.25 else (body if (c < o and uw < 0.15) else 0.0)
            out["UWick"] = _bg(_RED, f) if f >= 0.1 else "color:#94a3b8;"
        return out

    def _conf_row(row):
        out = pd.Series("", index=row.index)
        if "Conf%" not in row.index:
            return out
        try:
            conf = float(row["Conf%"])
            net = float(row["Bull−Bear"]) if "Bull−Bear" in row.index else 0.0
        except (TypeError, ValueError):
            return out
        f = min(1.0, conf / 100.0)
        if f < 0.05 or net == 0:
            out["Conf%"] = "color:#94a3b8;"
            return out
        r, g, b = (22, 163, 74) if net > 0 else (220, 38, 38)
        rr, gg, bb = (int(255 + (c - 255) * f) for c in (r, g, b))
        txt = "#ffffff" if f > 0.55 else "#0f172a"
        out["Conf%"] = f"background-color:rgb({rr},{gg},{bb});color:{txt};font-weight:700;"
        return out

    sty = ct.style
    sty = _m(sty, lambda v: _heat(v, _GREEN), "Reversal")
    sty = _m(sty, lambda v: _heat(v, _BLUE), "Uptrend")
    sty = _m(sty, lambda v: _heat(v, _RED), "Downtr")
    sty = _m(sty, lambda v: _heat(v, _AMBER), "Topping")
    sty = _m(sty, _net_css, "Final", "Bull−Bear")
    sty = _m(sty, _delta_css, "ΔVWAP")
    sty = _m(sty, _stretch_css, "Stretch")
    sty = _m(sty, _brd_css, "Brd%")
    sty = _m(sty, _clv_css, "Candle")
    sty = _m(sty, _hilo_css, "HiLo")
    sty = _m(sty, lambda v: "text-align:center;", "γ")
    sty = _m(sty, _vote_css, "P", "M", "V", "B", "S", "RSIdiv", "CVDdiv", "CVD↑", "Persist")
    sty = _m(sty, _state_css, "State")

    if "RSI" in ct.columns:
        _rsi_ch = pd.to_numeric(ct.iloc[::-1]["RSI"], errors="coerce")
        _rsi_fall = (_rsi_ch < _rsi_ch.shift(1)).reindex(ct.index)
        _rsi_map = {ix: _rsi_css(ct.at[ix, "RSI"], bool(_rsi_fall.get(ix, False)))
                    for ix in ct.index}
        sty = sty.apply(lambda col: [_rsi_map.get(ix, "") for ix in col.index],
                        subset=["RSI"], axis=0)

    if {"High", "Low", "%B"}.issubset(ct.columns):
        _ch = ct.iloc[::-1]
        _hi = pd.to_numeric(_ch["High"], errors="coerce")
        _lo = pd.to_numeric(_ch["Low"], errors="coerce")
        _ph = _hi.shift(1).rolling(3, min_periods=1).max()
        _pl = _lo.shift(1).rolling(3, min_periods=1).min()
        _new_hi = (_hi > _ph).reindex(ct.index)
        _new_lo = (_lo < _pl).reindex(ct.index)
        _hold_up = (_lo >= _pl).reindex(ct.index)
        _hold_dn = (_hi <= _ph).reindex(ct.index)
        _pb_map = {ix: _pctb_state_css(ct.at[ix, "%B"],
                                       bool(_new_hi.get(ix, False)), bool(_new_lo.get(ix, False)),
                                       bool(_hold_up.get(ix, True)), bool(_hold_dn.get(ix, True)))
                   for ix in ct.index}
        sty = sty.apply(lambda col: [_pb_map.get(ix, "") for ix in col.index],
                        subset=["%B"], axis=0)

    if {"Conf%", "Bull−Bear"}.issubset(ct.columns):
        sty = sty.apply(_conf_row, axis=1)
    if {"Open", "High", "Low", "Close"}.issubset(ct.columns) and ({"LWick", "UWick"} & set(ct.columns)):
        sty = sty.apply(_wick_row, axis=1)
    sty = sty.set_properties(**{"font-size": "13px"})
    sty = sty.format(na_rep="—", precision=1)
    return sty


def column_key_md(vwap_label: str = "fair value") -> str:
    """The legend markdown. vwap_label lets the 2H page say 'anchored VWAP'."""
    return (
        "**Column key** (results lead, then the inputs that produced them) — "
        "**`State`** the resulting call · **`Final`** = Bull−Bear × signal-agreement × dealer-gamma "
        "(where stored) — the trust-adjusted headline conviction (🟢 + bull / 🔴 − defend; ±35 agreed "
        "= act-worthy, near 0 = no edge) · **`γ`** that day's dealer-gamma regime (🟢 shock-absorber "
        "backs bull · 🔴 accelerator backs bear · — none stored / no login that day, so Final un-tilted) "
        "· **`Bull−Bear`** = bull-read − bear-read, the raw lean *before* the agreement & gamma "
        "adjustments · **`Brd%`** breadth (🟢 >55 broad / 🔴 <45 weak) · "
        "**`Conf%`** = net of the 4 pillars (agree − oppose) ÷ 4, tinted 🟢 when the lean is bullish / "
        "🔴 when bearish (darker = stronger; so 4-agree = 100%, 3-agree/1-neutral = 75%) · "
        f"`ΔVWAP` close minus {vwap_label} · `RSI` momentum, banded by regime (🟣 capitulation "
        "<30 · 🔴 downtrend 30–45 · ⚪ neutral 45–55 · 🟢 uptrend 55–70 · 🟠 overbought >70; **text "
        "turns red when RSI fell vs the previous candle**) · "
        "`RSIdiv` RSI divergence (🟢▲ bull / 🔴▼ bear) · `CVD↑` CVD rose vs the *previous* candle (🟢▲) · "
        "`CVDdiv` 6-bar volume divergence (🟢▲/🔴▼) · "
        "`HiLo` swing-high+low in one cell (🟢 ▲▲ uptrend · 🔴 ▼▼ downtrend · 🟠 ▲▼ expanding · ▼▲ inside) · "
        "`LWick` 🟢 bullish lower side — long lower wick (buyers rejected the low) *or* a green body with "
        "no lower wick (rose from the open) · `UWick` 🔴 bearish upper side — long upper wick (sellers) "
        "*or* a red body with no upper wick · `Candle` single close-location read (🟢 +1 closed at high / "
        "🔴 −1 at low) — captures momentum *and* rejection in one column (trial; compare vs LWick/UWick) · "
        f"`%B` momentum (position **confirmed by fast price structure**) + reversal: high %B *and* a fresh "
        "high → 🟢 up-momentum (pale green = high but no new high yet); low %B *and* a fresh low → 🔴 "
        "down-momentum; beyond a band but **not** making new highs/lows → 🟠 amber = stretched, "
        "mean-reversion watch; ~0.5 neutral · "
        f"`Stretch` signed stretch from {vwap_label}, heat-gradient (🟢 + above / 🔴 − below, in "
        "expected-moves) · `Persist` ↑N 🟢 / ↓N 🔴 = N candles in a row above / below VWAP · "
        "**`Reversal`** bounce-brewing, **`Uptrend`** ride-it (🟢 bull) · **`Downtr`** defend-PUT, "
        "**`Topping`** defend-CALL (🔴 bear) · "
        "`P/M/V/B/S` pillar votes · `Agree/Oppose` vote tally · *then raw* `O/H/L/C · VWAP · CVD`.")
