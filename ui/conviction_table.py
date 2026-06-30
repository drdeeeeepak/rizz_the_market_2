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
    sty = _m(sty, _net_css, "Final", "Bull−Bear", "γ")
    sty = _m(sty, _delta_css, "ΔVWAP")
    sty = _m(sty, _stretch_css, "Stretch")
    sty = _m(sty, _brd_css, "Brd%")
    sty = _m(sty, _clv_css, "Candle")
    sty = _m(sty, _hilo_css, "HiLo")
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


def candle_table_frozen_html(ct: pd.DataFrame, height: int = 670) -> str:
    """
    Render style_candle_table(ct) as a self-contained HTML table inside a scrollable
    box with a **frozen header AND frozen first data row** (the newest candle, since the
    table is newest-first). st.dataframe can't pin a data row, so we drop to HTML + CSS
    `position:sticky`; all the Styler cell colours are preserved inline.

    Use with: st.markdown(candle_table_frozen_html(ct), unsafe_allow_html=True)
    """
    _uuid = "p18ct"
    sty = style_candle_table(ct).hide(axis="index").set_uuid(_uuid)
    # Deterministic header height so the first row's sticky `top` lines up exactly.
    _hh = 30
    table_html = sty.to_html()
    # IMPORTANT: Styler emits per-cell colours in a <style> block keyed by cell ID
    # (`#T_p18ct_row0_col5`, specificity 1,0,0). Our white opaque backing for the frozen
    # row must therefore use a CLASS-ONLY selector (specificity 0,1,3) so coloured cells
    # win and keep their heat — only uncoloured cells fall back to white (prevents the
    # scrolling rows bleeding through). position/z-index/box-shadow never clash with
    # Styler, so those are safe at any specificity.
    css = f"""
<style>
.p18-frozen-wrap {{ max-height:{height}px; overflow:auto; position:relative;
                    border:1px solid #e2e8f0; border-radius:6px; }}
.p18-frozen-wrap table {{ border-collapse:separate; border-spacing:0; font-size:13px; }}
.p18-frozen-wrap th, .p18-frozen-wrap td {{ white-space:nowrap; padding:4px 8px;
                                            box-sizing:border-box; }}
/* frozen header (no Styler colours on headers → class backing is fine) */
.p18-frozen-wrap thead th {{ position:sticky; top:0; z-index:6; height:{_hh}px;
                             background:#f1f5f9; color:#0f172a; font-weight:700;
                             box-shadow:inset 0 -1px 0 #cbd5e1; }}
/* frozen first data row (newest candle) — sits just under the header */
.p18-frozen-wrap tbody tr:first-child td {{ position:sticky; top:{_hh}px; z-index:4;
                                            background:#ffffff;
                                            box-shadow:inset 0 -2px 0 #94a3b8; }}
</style>"""
    return f"{css}<div class='p18-frozen-wrap'>{table_html}</div>"


def column_key_md(vwap_label: str = "fair value") -> str:
    """The legend markdown. vwap_label lets the 2H page say 'anchored VWAP'."""
    return (
        "**Column key** (results lead, then the inputs that produced them) — "
        "**`State`** the resulting call · **`Final`** = Bull−Bear × signal-agreement — the "
        "trust-adjusted headline conviction *without* any dealer-gamma tilt (🟢 + bull / 🔴 − defend; "
        "±35 agreed = act-worthy, near 0 = no edge) · **`γ`** that **same figure with that day's "
        "dealer-gamma tilt folded in** (×1.15 if gamma backs the lean, ×0.85 if it fights — POSITIVE "
        "shock-absorber backs bull, NEGATIVE accelerator backs bear; compare vs `Final` to see gamma's "
        "push; — = none stored / no login that day) "
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


# ══════════════════════════════════════════════════════════════════════════════
# Vertical / transposed view — candles become COLUMNS (oldest→newest, newest on the
# RIGHT) and the signals become ROWS, so a handful of candles read top-to-bottom
# under each timestamp in one glance. Re-uses the per-value colour helpers above,
# dispatched by ROW name instead of column name.
# ══════════════════════════════════════════════════════════════════════════════

# Curated "headline + key reads" rows (top→bottom under each candle). The full set is
# every column candle_table() produced — shown when the page asks for all rows.
TRANSPOSED_KEY_ROWS = [
    "State", "Final", "γ", "Bull−Bear", "Conf%", "Brd%",
    "RSI", "RSIdiv", "ΔVWAP", "Stretch", "HiLo", "Candle", "%B", "Persist",
    "Reversal", "Uptrend", "Downtr", "Topping",
]


def transpose_candle_table(ct_chrono: pd.DataFrame, n: int = 8,
                           key_rows_only: bool = True):
    """
    Flip a chronological (oldest-first) candle_table() 90°.

    Returns (display, context):
      • display — the rows to SHOW (curated subset or all), columns = the last `n`
        candle timestamps oldest→newest (newest on the right).
      • context — the FULL transposed frame (all rows) for the same candles, so the
        styler can reach High/Low/Open/Close/Bull−Bear even when they're hidden.
    Pass a candle_table built with newest_first=False (oldest-first) so column order
    reads left→right in time.
    """
    if ct_chrono is None or ct_chrono.empty:
        return pd.DataFrame(), pd.DataFrame()
    tail = ct_chrono.tail(int(n))
    full = tail.set_index("Time").T            # rows = signals, cols = timestamps

    # Transposed, each candle COLUMN mixes strings/ints/floats (State + RSI + scores…),
    # which can't serialise to Arrow. Cast every cell to a tidy string so each column is
    # homogeneous; the styler reads the numbers back via float()/to_numeric, so colours
    # are unaffected. Values arrive pre-rounded from candle_table().
    def _cell(v):
        if pd.isna(v):
            return "—"
        if isinstance(v, float) and float(v).is_integer():
            return str(int(v))
        return str(v)
    full = full.apply(lambda col: col.map(_cell))   # Series.map: works on all pandas (3.0 dropped applymap)

    if key_rows_only:
        keep = [r for r in TRANSPOSED_KEY_ROWS if r in full.index]
        display = full.loc[keep]
    else:
        display = full
    return display, full


def style_transposed_table(display: pd.DataFrame, ctx: pd.DataFrame = None):
    """
    Style a transposed frame (signals as rows, candles as columns). Dispatches the
    same colour helpers used by style_candle_table(), but keyed by ROW name. `ctx`
    is the full transposed frame (all rows) for cross-row reads (%B structure, Conf%
    tint, wicks); defaults to `display` when not supplied.
    """
    if display is None or display.empty:
        return display.style if hasattr(display, "style") else display
    ctx = ctx if ctx is not None and not ctx.empty else display
    styles = pd.DataFrame("", index=display.index, columns=display.columns)
    cols = list(display.columns)

    def _crow(name):
        return ctx.loc[name] if name in ctx.index else None

    # ── simple per-value dispatch ──────────────────────────────────────────────
    _heat_base = {"Reversal": _GREEN, "Uptrend": _BLUE, "Downtr": _RED, "Topping": _AMBER}
    for name, base in _heat_base.items():
        if name in display.index:
            styles.loc[name] = [_heat(v, base) for v in display.loc[name]]
    for name in ("Final", "Bull−Bear", "γ"):
        if name in display.index:
            styles.loc[name] = [_net_css(v) for v in display.loc[name]]
    _simple = {"ΔVWAP": _delta_css, "Stretch": _stretch_css, "Brd%": _brd_css,
               "Candle": _clv_css, "HiLo": _hilo_css, "State": _state_css}
    for name, fn in _simple.items():
        if name in display.index:
            styles.loc[name] = [fn(v) for v in display.loc[name]]
    for name in ("P", "M", "V", "B", "S", "RSIdiv", "CVDdiv", "CVD↑", "Persist"):
        if name in display.index:
            styles.loc[name] = [_vote_css(v) for v in display.loc[name]]

    # ── RSI: previous candle = the column to the LEFT (time order) ──────────────
    if "RSI" in display.index:
        _rsi = pd.to_numeric(display.loc["RSI"], errors="coerce")
        _out, _prev = [], None
        for v in _rsi:
            falling = (_prev is not None and pd.notna(v) and pd.notna(_prev) and v < _prev)
            _out.append(_rsi_css(v, bool(falling)))
            _prev = v
        styles.loc["RSI"] = _out

    # ── Conf%: tint by the Bull−Bear sign in the SAME column ───────────────────
    if "Conf%" in display.index:
        _bb = pd.to_numeric(_crow("Bull−Bear"), errors="coerce") if _crow("Bull−Bear") is not None else None
        _out = []
        for i, v in enumerate(display.loc["Conf%"]):
            try:
                conf = float(v)
                net = float(_bb.iloc[i]) if _bb is not None else 0.0
            except (TypeError, ValueError):
                _out.append("")
                continue
            f = min(1.0, conf / 100.0)
            if f < 0.05 or net == 0:
                _out.append("color:#94a3b8;")
                continue
            r, g, b = (22, 163, 74) if net > 0 else (220, 38, 38)
            rr, gg, bb_ = (int(255 + (c - 255) * f) for c in (r, g, b))
            txt = "#ffffff" if f > 0.55 else "#0f172a"
            _out.append(f"background-color:rgb({rr},{gg},{bb_});color:{txt};font-weight:700;")
        styles.loc["Conf%"] = _out

    # ── %B: structure-aware, needs High/Low rows (previous = columns to the left)
    if "%B" in display.index and _crow("High") is not None and _crow("Low") is not None:
        _hi = pd.to_numeric(_crow("High"), errors="coerce")
        _lo = pd.to_numeric(_crow("Low"), errors="coerce")
        _ph = _hi.shift(1).rolling(3, min_periods=1).max()
        _pl = _lo.shift(1).rolling(3, min_periods=1).min()
        _out = []
        for i in range(len(cols)):
            new_hi = bool(_hi.iloc[i] > _ph.iloc[i]) if pd.notna(_ph.iloc[i]) else False
            new_lo = bool(_lo.iloc[i] < _pl.iloc[i]) if pd.notna(_pl.iloc[i]) else False
            hold_up = bool(_lo.iloc[i] >= _pl.iloc[i]) if pd.notna(_pl.iloc[i]) else True
            hold_dn = bool(_hi.iloc[i] <= _ph.iloc[i]) if pd.notna(_ph.iloc[i]) else True
            _out.append(_pctb_state_css(display.loc["%B"].iloc[i], new_hi, new_lo, hold_up, hold_dn))
        styles.loc["%B"] = _out

    # ── wicks: need OHLC rows (only present in show-all mode) ───────────────────
    if {"Open", "High", "Low", "Close"}.issubset(ctx.index) and ({"LWick", "UWick"} & set(display.index)):
        _o = pd.to_numeric(_crow("Open"), errors="coerce")
        _h = pd.to_numeric(_crow("High"), errors="coerce")
        _l = pd.to_numeric(_crow("Low"), errors="coerce")
        _c = pd.to_numeric(_crow("Close"), errors="coerce")
        for i in range(len(cols)):
            rng = _h.iloc[i] - _l.iloc[i]
            if not (rng > 0):
                continue
            lw = (min(_o.iloc[i], _c.iloc[i]) - _l.iloc[i]) / rng
            uw = (_h.iloc[i] - max(_o.iloc[i], _c.iloc[i])) / rng
            body = abs(_c.iloc[i] - _o.iloc[i]) / rng
            if "LWick" in display.index:
                f = lw if lw >= 0.25 else (body if (_c.iloc[i] > _o.iloc[i] and lw < 0.15) else 0.0)
                styles.loc["LWick"].iloc[i] = _bg(_GREEN, f) if f >= 0.1 else "color:#94a3b8;"
            if "UWick" in display.index:
                f = uw if uw >= 0.25 else (body if (_c.iloc[i] < _o.iloc[i] and uw < 0.15) else 0.0)
                styles.loc["UWick"].iloc[i] = _bg(_RED, f) if f >= 0.1 else "color:#94a3b8;"

    sty = display.style.apply(lambda _: styles, axis=None)
    sty = sty.set_properties(**{"font-size": "13px", "text-align": "center"})
    sty = sty.format(na_rep="—", precision=1)
    return sty
