# pages/31_RSI_Divergence_Backtest.py
# Dedicated backtest for RSI divergence-only trading strategy
# Tests: Price makes new extreme (high/low) but RSI does NOT confirm it
# Entry: LONG on bullish divergence (price low + RSI higher)
#        SHORT on bearish divergence (price high + RSI lower)

import importlib
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import data.live_fetcher as _lf
from analytics import rsi_fade_backtest as rfb

try:
    importlib.reload(_lf)
    importlib.reload(rfb)
except Exception:
    pass

st.set_page_config(page_title="P31 · RSI Divergence Backtest", layout="wide")

st.title("RSI Divergence-Only Backtest")
st.caption(
    "Pure divergence trading: Price makes new extreme but RSI doesn't confirm. "
    "LONG on bullish divergence, SHORT on bearish divergence. "
    "No stop loss, no target, no time stop, no midline exit — a trade runs until the "
    "opposite divergence fires, which closes it and opens the trade the other way."
)

# ══════════════════════════════════════════════════════════════════════════════
# FETCH DATA
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def fetch_historical_data():
    """Fetch maximum available 30m and 60m (hourly) OHLC data from Kite"""
    try:
        df_30m = _lf.get_nifty_30m(days=365)
        df_60m = _lf.get_nifty_1h_phase(days=365)
        return df_30m, df_60m
    except Exception as e:
        st.error(f"Failed to fetch data: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, None

df_hist_30m, df_hist_60m = fetch_historical_data()

if df_hist_30m is None or df_hist_30m.empty:
    st.error("❌ Could not fetch historical 30m data")
    st.stop()

if df_hist_60m is None or df_hist_60m.empty:
    st.error("❌ Could not fetch historical 60m data")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG: Divergence Parameters
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("Divergence Configuration")

col1, col2 = st.columns(2)

with col1:
    div_lookback = st.slider(
        "Lookback period (bars for divergence detection)",
        min_value=10, max_value=50, value=20, step=5
    )

with col2:
    div_min_gap = st.slider(
        "Minimum RSI divergence gap (points)",
        min_value=0.5, max_value=5.0, value=2.0, step=0.5
    )

st.caption(
    f"30m: {len(df_hist_30m)} candles "
    f"({df_hist_30m.index[0]:%d %b %Y} → {df_hist_30m.index[-1]:%d %b %Y})  ·  "
    f"60m: {len(df_hist_60m)} candles "
    f"({df_hist_60m.index[0]:%d %b %Y} → {df_hist_60m.index[-1]:%d %b %Y})"
)

# ══════════════════════════════════════════════════════════════════════════════
# RUN BACKTEST
# ══════════════════════════════════════════════════════════════════════════════

with st.spinner("Running divergence-only backtest on 30m & 60m data..."):
    try:
        # 30m — divergence is the only entry rule
        trades_30m = rfb.simulate_pure_divergence_trades(
            df_hist_30m, rsi_period=14,
            div_lookback=div_lookback, div_min_gap=div_min_gap
        )
        stats_30m = rfb.trade_stats(trades_30m)

        # 60m — divergence is the only entry rule
        trades_60m = rfb.simulate_pure_divergence_trades(
            df_hist_60m, rsi_period=14,
            div_lookback=div_lookback, div_min_gap=div_min_gap
        )
        stats_60m = rfb.trade_stats(trades_60m)

        # Combined
        if not trades_30m.empty and not trades_60m.empty:
            combined_trades = pd.concat([trades_30m, trades_60m], ignore_index=True)
        elif not trades_30m.empty:
            combined_trades = trades_30m.copy()
        else:
            combined_trades = trades_60m.copy()

        combined_stats = rfb.trade_stats(combined_trades)

        st.success("✅ Backtest complete!")

        # ══════════════════════════════════════════════════════════════════════════════
        # METRICS
        # ══════════════════════════════════════════════════════════════════════════════

        st.divider()
        st.subheader("Results: 30m Timeframe")

        m_30m_1, m_30m_2, m_30m_3, m_30m_4, m_30m_5 = st.columns(5)

        with m_30m_1:
            st.metric("Trades", stats_30m['n_trades'])

        with m_30m_2:
            st.metric("Win Rate", f"{stats_30m['win_rate']:.1f}%")

        with m_30m_3:
            st.metric("Expectancy", f"{stats_30m['expectancy_pts']:.2f} pts/trade")

        with m_30m_4:
            st.metric("Profit Factor", f"{stats_30m['profit_factor']:.2f}")

        with m_30m_5:
            st.metric("Total P&L", f"{stats_30m['total_pnl_pts']:.0f} pts")

        m_30m_6, m_30m_7, m_30m_8 = st.columns(3)

        with m_30m_6:
            st.metric("Max Drawdown", f"{stats_30m['max_drawdown_pts']:.0f} pts")

        with m_30m_7:
            st.metric("Avg Win", f"{stats_30m['avg_win_pts']:.2f} pts")

        with m_30m_8:
            st.metric("Avg Loss", f"{stats_30m['avg_loss_pts']:.2f} pts")

        # 60m metrics
        st.divider()
        st.subheader("Results: 60m Timeframe")

        m_60m_1, m_60m_2, m_60m_3, m_60m_4, m_60m_5 = st.columns(5)

        with m_60m_1:
            st.metric("Trades", stats_60m['n_trades'])

        with m_60m_2:
            st.metric("Win Rate", f"{stats_60m['win_rate']:.1f}%")

        with m_60m_3:
            st.metric("Expectancy", f"{stats_60m['expectancy_pts']:.2f} pts/trade")

        with m_60m_4:
            st.metric("Profit Factor", f"{stats_60m['profit_factor']:.2f}")

        with m_60m_5:
            st.metric("Total P&L", f"{stats_60m['total_pnl_pts']:.0f} pts")

        m_60m_6, m_60m_7, m_60m_8 = st.columns(3)

        with m_60m_6:
            st.metric("Max Drawdown", f"{stats_60m['max_drawdown_pts']:.0f} pts")

        with m_60m_7:
            st.metric("Avg Win", f"{stats_60m['avg_win_pts']:.2f} pts")

        with m_60m_8:
            st.metric("Avg Loss", f"{stats_60m['avg_loss_pts']:.2f} pts")

        # Combined metrics
        st.divider()
        st.subheader("Results: Combined (30m + 60m)")

        m_c_1, m_c_2, m_c_3, m_c_4, m_c_5 = st.columns(5)

        with m_c_1:
            st.metric("Total Trades", combined_stats['n_trades'])

        with m_c_2:
            st.metric("Win Rate", f"{combined_stats['win_rate']:.1f}%")

        with m_c_3:
            st.metric("Expectancy", f"{combined_stats['expectancy_pts']:.2f} pts/trade")

        with m_c_4:
            st.metric("Profit Factor", f"{combined_stats['profit_factor']:.2f}")

        with m_c_5:
            st.metric("Total P&L", f"{combined_stats['total_pnl_pts']:.0f} pts")

        # ══════════════════════════════════════════════════════════════════════════════
        # STOP-LOSS SWEEP — the optimum SL, measured on real candles
        # ══════════════════════════════════════════════════════════════════════════════

        st.divider()
        st.subheader("Optimum Stop Loss")
        st.caption(
            "Each row is a COMPLETE re-run of the backtest with that stop in place, "
            "checked against every bar's intrabar low (long) / high (short) — not the "
            "finished trade log with its losses clipped. A stop also knocks out winners "
            "that dipped through it before recovering, and it changes every entry that "
            "follows, so clipping a trade log always flatters a tight stop."
        )

        STOPS = [50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 600, 800, 0]

        def _show_sweep(df_tf, label, key):
            sweep = rfb.stop_sweep(df_tf, STOPS, rsi_period=14,
                                   div_lookback=div_lookback, div_min_gap=div_min_gap)
            disp = sweep.copy()
            disp["stop_pts"] = disp["stop_pts"].apply(
                lambda v: "no stop" if pd.isna(v) else f"{v:.0f}")
            st.markdown(f"**{label}**")
            st.dataframe(
                disp.style.format({
                    "win_rate": "{:.1f}%", "stopped_pct": "{:.1f}%",
                    "expectancy_pts": "{:+.1f}", "profit_factor": "{:.2f}",
                    "total_pnl_pts": "{:+.0f}", "max_drawdown_pts": "{:.0f}",
                    "avg_win_pts": "{:+.0f}", "avg_loss_pts": "{:+.0f}",
                    "avg_bars_held": "{:.0f}",
                }).background_gradient(subset=["expectancy_pts"], cmap="RdYlGn"),
                use_container_width=True, hide_index=True,
            )
            valid = sweep.dropna(subset=["expectancy_pts"])
            if not valid.empty:
                best = valid.loc[valid["expectancy_pts"].idxmax()]
                base = sweep[sweep["stop_pts"].isna()]
                base_exp = float(base["expectancy_pts"].iloc[0]) if not base.empty else float("nan")
                tag = "no stop" if pd.isna(best["stop_pts"]) else f"{best['stop_pts']:.0f} pts"
                st.success(
                    f"Best expectancy on {label}: **{tag}** → "
                    f"{best['expectancy_pts']:+.1f} pts/trade over {int(best['n_trades'])} trades "
                    f"(PF {best['profit_factor']:.2f}, total {best['total_pnl_pts']:+.0f} pts, "
                    f"max DD {best['max_drawdown_pts']:.0f}). "
                    f"No stop = {base_exp:+.1f} pts/trade."
                )
            return sweep

        _show_sweep(df_hist_30m, "30m", "sw30")
        _show_sweep(df_hist_60m, "60m", "sw60")

        # How far trades actually go against you — the constraint any stop has to clear
        if not combined_trades.empty and "mae_pts" in combined_trades.columns:
            w = combined_trades[combined_trades["pnl_pts"] > 0]["mae_pts"]
            l = combined_trades[combined_trades["pnl_pts"] <= 0]["mae_pts"]
            if not w.empty:
                st.markdown(
                    "**How far trades go against you before resolving (MAE, points)** — "
                    "a stop tighter than the winners' MAE turns those winners into losses:"
                )
                mae_tbl = pd.DataFrame({
                    "median": [w.median(), l.median() if not l.empty else float("nan")],
                    "75th pct": [w.quantile(.75), l.quantile(.75) if not l.empty else float("nan")],
                    "90th pct": [w.quantile(.90), l.quantile(.90) if not l.empty else float("nan")],
                    "max": [w.max(), l.max() if not l.empty else float("nan")],
                }, index=["winning trades", "losing trades"]).round(0)
                st.dataframe(mae_tbl, use_container_width=True)

        # ══════════════════════════════════════════════════════════════════════════════
        # RECENT TRADES TABLE
        # ══════════════════════════════════════════════════════════════════════════════

        st.divider()
        st.subheader("Recent Divergence Trades (Last 20)")

        if not combined_trades.empty:
            display_df = combined_trades.sort_values('entry_time', ascending=False).head(20).copy()
            display_df['entry_time'] = pd.to_datetime(display_df['entry_time']).dt.strftime('%Y-%m-%d %H:%M')
            display_df['exit_time'] = pd.to_datetime(display_df['exit_time']).dt.strftime('%Y-%m-%d %H:%M')

            cols_to_show = ['entry_time', 'side', 'entry_price', 'entry_rsi', 'exit_price',
                            'pnl_pts', 'pnl_pct', 'mae_pts', 'bars_held', 'exit_reason']
            st.dataframe(display_df[cols_to_show], use_container_width=True, hide_index=True)
        else:
            st.info("No trades generated")

        # ══════════════════════════════════════════════════════════════════════════════
        # EQUITY CURVE
        # ══════════════════════════════════════════════════════════════════════════════

        if not combined_trades.empty:
            st.divider()
            st.subheader("Equity Curve")

            equity = combined_trades[["exit_time", "pnl_pts"]].copy()
            equity["cum_pnl_pts"] = equity["pnl_pts"].cumsum()
            equity["exit_time"] = pd.to_datetime(equity["exit_time"])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=equity["exit_time"],
                y=equity["cum_pnl_pts"],
                mode="lines+markers",
                line=dict(color="#3b82f6", width=2),
                marker=dict(size=5),
                name="Cumulative P&L"
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig.update_layout(
                height=400,
                xaxis_title="Exit Time",
                yaxis_title="Cumulative P&L (pts)",
                hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)

        # ══════════════════════════════════════════════════════════════════════════════
        # CSV DOWNLOADS
        # ══════════════════════════════════════════════════════════════════════════════

        st.divider()
        st.subheader("Download Results")

        col_30m, col_60m, col_combined = st.columns(3)

        with col_30m:
            if not trades_30m.empty:
                csv_30m = trades_30m.to_csv(index=False)
                st.download_button(
                    "⬇ 30m Divergence Trades CSV",
                    csv_30m.encode('utf-8'),
                    file_name="divergence_30m_trades.csv",
                    mime="text/csv",
                    key="div_30m_csv"
                )
            else:
                st.info("No 30m trades")

        with col_60m:
            if not trades_60m.empty:
                csv_60m = trades_60m.to_csv(index=False)
                st.download_button(
                    "⬇ 60m Divergence Trades CSV",
                    csv_60m.encode('utf-8'),
                    file_name="divergence_60m_trades.csv",
                    mime="text/csv",
                    key="div_60m_csv"
                )
            else:
                st.info("No 60m trades")

        with col_combined:
            if not combined_trades.empty:
                csv_combined = combined_trades.to_csv(index=False)
                st.download_button(
                    "⬇ All Divergence Trades CSV",
                    csv_combined.encode('utf-8'),
                    file_name="divergence_all_trades.csv",
                    mime="text/csv",
                    key="div_all_csv"
                )
            else:
                st.info("No combined trades")

        # ══════════════════════════════════════════════════════════════════════════════
        # SUMMARY STATISTICS
        # ══════════════════════════════════════════════════════════════════════════════

        st.divider()
        st.subheader("Summary Statistics")

        summary_text = f"""
### 30m Trades
- **Total Trades:** {stats_30m['n_trades']} (LONG {stats_30m['long_trades']} | SHORT {stats_30m['short_trades']})
- **Win Rate:** {stats_30m['win_rate']:.1f}%
- **Profit Factor:** {stats_30m['profit_factor']:.2f}
- **Expectancy:** {stats_30m['expectancy_pts']:.2f} pts/trade
- **Avg Win:** {stats_30m['avg_win_pts']:.2f} pts | **Avg Loss:** {stats_30m['avg_loss_pts']:.2f} pts
- **Total P&L:** {stats_30m['total_pnl_pts']:.0f} pts
- **Max Drawdown:** {stats_30m['max_drawdown_pts']:.0f} pts
- **Avg Hold:** {stats_30m['avg_bars_held']:.1f} candles (~{stats_30m['avg_bars_held']*30:.0f} min)

### 60m Trades
- **Total Trades:** {stats_60m['n_trades']} (LONG {stats_60m['long_trades']} | SHORT {stats_60m['short_trades']})
- **Win Rate:** {stats_60m['win_rate']:.1f}%
- **Profit Factor:** {stats_60m['profit_factor']:.2f}
- **Expectancy:** {stats_60m['expectancy_pts']:.2f} pts/trade
- **Avg Win:** {stats_60m['avg_win_pts']:.2f} pts | **Avg Loss:** {stats_60m['avg_loss_pts']:.2f} pts
- **Total P&L:** {stats_60m['total_pnl_pts']:.0f} pts
- **Max Drawdown:** {stats_60m['max_drawdown_pts']:.0f} pts
- **Avg Hold:** {stats_60m['avg_bars_held']:.1f} candles (~{stats_60m['avg_bars_held']*60:.0f} min)

### Combined (30m + 60m)
- **Total Trades:** {combined_stats['n_trades']}
- **Win Rate:** {combined_stats['win_rate']:.1f}%
- **Profit Factor:** {combined_stats['profit_factor']:.2f}
- **Expectancy:** {combined_stats['expectancy_pts']:.2f} pts/trade
- **Total P&L:** {combined_stats['total_pnl_pts']:.0f} pts
- **Max Drawdown:** {combined_stats['max_drawdown_pts']:.0f} pts
        """
        st.markdown(summary_text)

    except Exception as e:
        st.error(f"❌ Backtest failed: {str(e)}")
        import traceback
        traceback.print_exc()
