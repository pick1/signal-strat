#!/usr/bin/env python3
"""
TRADING SIGNALS — Financial Intelligence & Strategy Dashboard
==============================================================
Analyses financial news/articles and generates actionable trading strategies.

Run: streamlit run app.py
"""

import json
import re
import time
import urllib.parse
from datetime import datetime

import streamlit as st

from trading_signals.config import (
    PROJECT_DIR,
    CAT_COLORS,
    CAT_LABELS,
    CAT_DESCRIPTIONS,
)
from trading_signals.db import get_db, load_entries, save_entry, delete_entry
from trading_signals.auth import is_password_set, verify_password, set_password
from trading_signals.scrapers import (
    detect_input_type,
    fetch_url_content,
    extract_tickers,
    is_financial_url,
)
from trading_signals.analyzer import analyze_content, set_notification_callback
from trading_signals.strategy_engine import (
    create_strategies,
    load_strategies,
    update_strategy_status,
    delete_strategy,
    get_strategy_stats,
    format_strategy_for_display,
)
from trading_signals.portfolio import (
    set_holdings,
    get_holdings,
    add_holding,
    remove_holding,
    set_watchlist,
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    set_risk_profile,
    get_risk_profile,
    build_portfolio_context,
)


# ─── Wire notifications ──────────────────────────────────────────────────────
set_notification_callback(lambda msg, icon: st.toast(msg, icon=icon))


# ─── PAGE SETUP ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TRADING SIGNALS — Financial Intelligence",
    page_icon="/📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono:ital,wght@0,300;0,400;1,300&display=swap');
html, body, [class*="css"] { font-family: 'DM Mono', monospace; }
.signal-header { font-family: 'Syne', sans-serif; font-size: 28px; font-weight: 800; color: #00ff88; letter-spacing: 0.15em; text-shadow: 0 0 30px rgba(0,255,136,0.4); margin-bottom: 0; }
.signal-sub { font-size: 10px; letter-spacing: 0.3em; color: #404060; text-transform: uppercase; margin-top: 0; }
.card { background: #111118; border: 1px solid #252535; border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; border-left-width: 3px; }
.card-title { font-family: 'Syne', sans-serif; font-size: 17px; font-weight: 700; margin-bottom: 8px; }
.tag { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; border: 1px solid; margin-right: 4px; margin-bottom: 4px; }
.section-label { font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #404060; margin-bottom: 4px; }
.section-text { font-size: 12px; color: #9090b0; line-height: 1.6; }
.verdict-text { font-style: italic; font-size: 13px; color: #e8e8f0; line-height: 1.6; }
.strategy-card { background: #0f0f18; border: 1px solid #4488ff33; border-radius: 8px; padding: 12px 14px; margin-bottom: 8px; }
.metric-box { background: #0a0a0f; border: 1px solid #252535; border-radius: 8px; padding: 12px; text-align: center; }
.metric-value { font-family: 'Syne', sans-serif; font-size: 24px; font-weight: 700; }
.metric-label { font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase; color: #404060; }
.win { color: #00ff88; }
.loss { color: #ff4466; }
</style>""", unsafe_allow_html=True)


# ─── AUTH GATE ────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated"):
    st.markdown(
        '<div class="signal-header" style="text-align:center;margin-top:40px">📈 TRADING SIGNALS</div>'
        '<div class="signal-sub" style="text-align:center">Financial Intelligence & Strategy Dashboard</div>',
        unsafe_allow_html=True,
    )

    if not is_password_set():
        st.markdown('<div style="max-width:360px;margin:40px auto">', unsafe_allow_html=True)
        st.markdown("**Set a password** to secure this dashboard.")
        pw = st.text_input("Password", type="password", key="setup_pw")
        pw2 = st.text_input("Confirm", type="password", key="setup_pw2")
        if st.button("Set Password", type="primary", use_container_width=True):
            if pw and pw == pw2 and len(pw) >= 4:
                set_password(pw)
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Password must be 4+ chars and match.")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div style="max-width:360px;margin:40px auto">', unsafe_allow_html=True)
        pw = st.text_input("Password", type="password", key="login_pw")
        if st.button("Unlock", type="primary", use_container_width=True):
            if verify_password(pw):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.stop()


# ─── RENDERERS ────────────────────────────────────────────────────────────────


def render_analysis_card(entry):
    """Render a financial analysis entry as a styled card."""
    cat = entry.get("category", "neutral")
    color = CAT_COLORS.get(cat, "#888")
    label = CAT_LABELS.get(cat, cat)

    raw_conf = entry.get("confidence", 0.8)
    if isinstance(raw_conf, str):
        try:
            raw_conf = float(raw_conf)
        except ValueError:
            raw_conf = 0.8
    conf = round(raw_conf * 100)

    tags = entry.get("tags", [])
    tickers = entry.get("tickers", [])
    date = entry.get("created_at", "")[:10]

    cat_tag = f'<span class="tag" style="color:{color};border-color:{color};background:rgba(0,0,0,0.3)">{label}</span>'

    ticker_tags = ""
    for t in tickers:
        ticker_tags += f'<span class="tag" style="color:#ffcc00;border-color:#ffcc0033;background:rgba(255,204,0,0.08)">${t}</span>'

    topic_tags = ""
    for t in tags:
        topic_tags += f'<span class="tag" style="color:#7070a0;border-color:#353550">{t}</span>'

    src_type = entry.get("source_type", "?")
    src_tag = f'<span class="tag" style="color:#7070a0;border-color:#353550">{src_type}</span>'

    raw_url = entry.get("raw_url")
    summary = entry.get("summary", "")
    verdict = entry.get("verdict", "")
    market_impact = entry.get("market_impact", "")
    key_metrics = entry.get("key_metrics", [])
    catalyst_date = entry.get("catalyst_date", "")
    next_steps_raw = entry.get("next_steps", [])

    # Metrics
    metrics_html = ""
    if key_metrics:
        metrics_html = '<div style="margin:10px 0;background:#0a0a0f;border:1px solid #252535;border-radius:8px;padding:10px 12px">'
        metrics_html += '<div class="section-label">Key Metrics</div>'
        for m in key_metrics:
            metrics_html += f'<div style="font-size:11px;color:#a0a0c0;margin:2px 0">▸ {m}</div>'
        metrics_html += '</div>'

    # Catalyst date
    cat_date_html = ""
    if catalyst_date:
        cat_date_html = f'<span class="tag" style="color:#ff66aa;border-color:#ff66aa33">📅 {catalyst_date}</span>'

    # Next steps
    next_steps_html = ""
    for s in next_steps_raw:
        next_steps_html += "▸ " + str(s) + "<br>"
    if not next_steps_html:
        next_steps_html = "none"

    # AI copy prompt
    ai_prompt = (
        f"{entry.get('title', 'Untitled')}\n\n"
        f"Summary: {summary}\n\n"
        f"Verdict: {verdict}\n\n"
        f"Category: {label}\n"
        f"Tickers: {', '.join(tickers)}\n"
        f"Market Impact: {market_impact}\n"
        f"Source: {raw_url or src_type}"
    )
    encoded_prompt = urllib.parse.quote(ai_prompt)
    copy_btn = (
        f'<button class="sl-copy-btn" data-clipboard="{encoded_prompt}" '
        f'style="background:none;border:1px solid #353550;color:#44aaff;border-radius:4px;'
        f'padding:2px 8px;font-size:10px;cursor:pointer;margin-right:10px">'
        f'📋 Copy</button>'
    )

    # Market impact
    impact_html = ""
    if market_impact:
        impact_html = (
            '<div style="background:#0a0a0f;border:1px solid #252535;border-radius:8px;padding:10px 14px;margin-bottom:10px">'
            '<div class="section-label">Market Impact</div>'
            f'<div class="section-text">{market_impact}</div>'
            '</div>'
        )

    return (
        '<div class="card" style="border-left-color:' + color + '">'
        '<div class="card-title">' + entry.get("title", "Untitled") + '</div>'
        '<div style="margin-bottom:10px">' + cat_tag + src_tag + cat_date_html + ticker_tags + topic_tags + '</div>'
        '<div class="section-text" style="margin-bottom:12px">' + summary + '</div>'
        + impact_html +
        '<div style="background:#0a0a0f;border:1px solid #252535;border-radius:8px;padding:10px 14px;margin-bottom:10px">'
          '<div class="section-label">Verdict</div>'
          '<div class="verdict-text">' + verdict + '</div>'
        '</div>'
        + metrics_html +
        '<div style="display:flex;gap:16px;margin-bottom:10px">'
          '<div style="flex:1;background:#0a0a0f;border:1px solid #353550;border-radius:8px;padding:10px 12px">'
            '<div class="section-label">Next Steps</div>'
            '<div class="section-text">' + next_steps_html + '</div>'
          '</div>'
        '</div>'
        '<div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid #252535;padding-top:8px">'
          '<span style="color:#404060;font-size:11px">' + copy_btn + date + '</span>'
          '<span style="font-size:11px">'
            + (('<a href="' + raw_url + '" target="_blank" style="color:#44aaff;text-decoration:none;margin-right:10px">View source →</a>' if raw_url else '') or '<span style="color:#353550;font-size:10px;margin-right:10px">via ' + src_type + '</span>') +
            'confidence ' + str(conf) + '%'
            '<span style="display:inline-block;width:60px;height:4px;background:#252535;border-radius:2px;vertical-align:middle;margin-left:6px">'
              '<span style="display:block;width:' + str(conf) + '%;height:100%;background:' + color + ';border-radius:2px"></span>'
            '</span>'
          '</span>'
        '</div>'
        '</div>'
    )


def render_strategy_card(strategy):
    """Render a trading strategy in a compact card."""
    ticker = strategy.get("ticker", "?")
    strat_type = strategy.get("strategy_type", "?")
    direction = strategy.get("direction", "neutral")
    status = strategy.get("status", "active")
    confidence = strategy.get("confidence", 0.5)
    risk = strategy.get("risk_level", "medium")

    # Status badge
    status_colors = {
        "active": "#4488ff",
        "entered": "#aa66ff",
        "monitoring": "#ffaa00",
        "closed_win": "#00ff88",
        "closed_loss": "#ff4466",
        "expired": "#606080",
        "cancelled": "#404060",
    }
    status_color = status_colors.get(status, "#606080")

    # Direction icon
    dir_icons = {"bullish": "🔼", "bearish": "🔽", "neutral": "➡️"}
    dir_icon = dir_icons.get(direction, "➡️")

    # P&L
    pnl = strategy.get("pnl_pct")
    pnl_str = ""
    if pnl is not None:
        cls = "win" if pnl >= 0 else "loss"
        pnl_str = f'<span class="{cls}" style="font-weight:700">{pnl:+.2f}%</span>'

    return f"""
    <div class="strategy-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div>
                <span style="font-family:'Syne',sans-serif;font-size:15px;font-weight:700">{dir_icon} {ticker}</span>
                <span class="tag" style="color:{status_color};border-color:{status_color}33;background:rgba(0,0,0,0.3)">{status.upper()}</span>
                <span class="tag" style="color:#7070a0;border-color:#353550">{strat_type}</span>
            </div>
            <div style="font-size:11px;color:#808090">Risk: {risk} · Conf: {confidence:.0%} {pnl_str}</div>
        </div>
        <div style="font-size:11px;color:#a0a0c0;margin-bottom:6px">{strategy.get('rationale', '')}</div>
        <div style="display:flex;gap:20px;font-size:11px;color:#606080">
            <div><span style="color:#7070a0">Entry:</span> {strategy.get('suggested_entry', 'N/A')}</div>
            <div><span style="color:#ff4466">Stop:</span> {strategy.get('stop_loss', 'none') or 'none'}</div>
            <div><span style="color:#00ff88">Target:</span> {strategy.get('take_profit', 'none') or 'none'}</div>
        </div>
    </div>
    """


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="signal-header">📈 TRADING SIGNALS</div>', unsafe_allow_html=True)
    st.markdown('<div class="signal-sub">Financial Intelligence & Strategy Dashboard</div>', unsafe_allow_html=True)
    st.divider()

    st.markdown("**Provider**")
    provider_options = ["OpenCode Zen", "Ollama (local)"]
    provider_choice = st.selectbox(
        "Provider", provider_options,
        index=1,
        label_visibility="collapsed",
    )
    provider = "openai" if "OpenCode" in provider_choice else "ollama"

    st.markdown("**Analysis Depth**")
    tier_options = ["Auto (per source type)", "Light", "Default", "Deep"]
    tier_choice = st.selectbox(
        "Tier", tier_options,
        index=0,
        label_visibility="collapsed",
    )
    tier_map = {"Auto (per source type)": None, "Light": "light", "Default": "default", "Deep": "deep"}
    tier_override = tier_map[tier_choice]

    # Generate strategies toggle
    gen_strategies = st.checkbox("Generate trading strategies", value=True,
                                  help="After analysis, generate actionable trading strategies")

    if st.button("🔒 Lock", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

    st.divider()

    # ── Tabs in sidebar ──
    sidebar_tab = st.radio("", ["New Entry", "Portfolio", "Risk Profile"], label_visibility="collapsed")

    if sidebar_tab == "New Entry":
        st.markdown("**New Entry**")
        input_text = st.text_area(
            "Paste financial news or URL",
            height=180,
            placeholder="Paste article text, URL to financial news article, earnings report...\n\nURLs are fetched and scraped automatically.",
            label_visibility="collapsed",
        )
        source_override = st.selectbox("Source type", [
            "Auto-detect", "Article", "URL"
        ])
        analyze_btn = st.button("📊 ANALYZE", use_container_width=True, type="primary")

    elif sidebar_tab == "Portfolio":
        st.markdown("**Current Holdings**")
        holdings = get_holdings()
        if holdings:
            for h in holdings:
                col1, col2 = st.columns([3, 1])
                col1.markdown(f"**${h.get('ticker', '?')}** — {h.get('shares', 0)} shares @ ${h.get('avg_cost', 0):.2f}")
                if col2.button("✕", key=f"rm_holding_{h.get('ticker')}", help="Remove"):
                    remove_holding(h.get('ticker', ''))
                    st.rerun()
        else:
            st.caption("No holdings configured.")

        st.markdown("**Add Holding**")
        add_ticker = st.text_input("Ticker", placeholder="AAPL", key="add_ticker", label_visibility="collapsed")
        col1, col2 = st.columns(2)
        add_shares = col1.number_input("Shares", min_value=1, value=1, key="add_shares")
        add_cost = col2.number_input("Avg Cost", min_value=0.01, value=100.0, key="add_cost", format="%.2f")
        if st.button("Add Holding", use_container_width=True):
            if add_ticker.strip():
                add_holding(add_ticker.strip(), int(add_shares), float(add_cost))
                st.toast(f"Added {add_ticker.upper()}", icon="✅")
                st.rerun()

        st.divider()
        st.markdown("**Watchlist**")
        watchlist = get_watchlist()
        if watchlist:
            st.markdown(", ".join(f"**${w}**" for w in watchlist))
        wl_ticker = st.text_input("Add to watchlist", placeholder="TICKER", key="wl_add", label_visibility="collapsed")
        if st.button("Add to Watchlist", use_container_width=True):
            if wl_ticker.strip():
                add_to_watchlist(wl_ticker.strip())
                st.toast(f"Added ${wl_ticker.upper()}", icon="⭐")
                st.rerun()

    elif sidebar_tab == "Risk Profile":
        profile = get_risk_profile()
        risk_tolerance = st.selectbox("Risk Tolerance",
            ["conservative", "moderate", "aggressive"],
            index=["conservative", "moderate", "aggressive"].index(profile.get("risk_tolerance", "moderate")))
        trading_style = st.selectbox("Trading Style",
            ["value", "growth", "momentum", "income", "blend"],
            index=["value", "growth", "momentum", "income", "blend"].index(profile.get("trading_style", "growth")))
        experience = st.selectbox("Experience Level",
            ["beginner", "intermediate", "advanced"],
            index=["beginner", "intermediate", "advanced"].index(profile.get("experience_level", "intermediate")))
        max_pos = st.slider("Max Position Size (%)", 5, 100, profile.get("max_position_size_pct", 25))
        account_value = st.number_input("Account Value ($)", min_value=0, value=profile.get("account_value", 0), step=1000)

        if st.button("Save Profile", use_container_width=True, type="primary"):
            set_risk_profile({
                "risk_tolerance": risk_tolerance,
                "trading_style": trading_style,
                "experience_level": experience,
                "max_position_size_pct": max_pos,
                "account_value": float(account_value),
                "max_drawdown_pct": profile.get("max_drawdown_pct", 15),
            })
            st.toast("Profile saved", icon="✅")

    st.divider()

    # ── Feed Controls ──
    st.markdown("**Filter Feed**")
    search_query = st.text_input("Search", placeholder="keyword or $TICKER...", label_visibility="collapsed")
    cat_filter = st.multiselect(
        "Categories",
        options=list(CAT_LABELS.keys()),
        format_func=lambda x: f"{CAT_LABELS[x]} — {CAT_DESCRIPTIONS.get(x, '')}",
        label_visibility="collapsed",
    )

    # ── Current View Toggle ──
    st.divider()
    view_mode = st.radio("View", ["📰 Feed", "📊 Strategies"], label_visibility="collapsed")

    st.divider()
    entries_all = load_entries()
    if entries_all:
        md_lines = ["# TRADING SIGNALS — Financial Intelligence", "_Exported " + datetime.now().strftime("%Y-%m-%d") + "_", ""]
        for cat, label in CAT_LABELS.items():
            group = [e for e in entries_all if e.get("category") == cat]
            if not group:
                continue
            md_lines += ["## " + label, ""]
            for e in group:
                md_lines += [
                    "### " + e.get("title", "Untitled"),
                    "**Tickers:** " + ", ".join(e.get("tickers", [])) + " | **Date:** " + e.get("created_at", "")[:10],
                    "", e.get("summary", ""), "",
                    "**Market Impact:** " + e.get("market_impact", ""),
                    "**Verdict:** _" + e.get("verdict", "") + "_",
                    "**Confidence:** " + str(round((e.get("confidence", 0.8) or 0.8) * 100)) + "%",
                    "", "---", ""
                ]
        st.download_button("Export Markdown", "\n".join(md_lines),
                           file_name="trading-signals-digest.md", mime="text/markdown",
                           use_container_width=True)
        st.download_button("Export JSON", json.dumps(entries_all, indent=2),
                           file_name="trading-signals-digest.json", mime="application/json",
                           use_container_width=True)
        if st.button("🗑️ Clear All", use_container_width=True):
            if st.session_state.get("confirm_clear"):
                get_db().truncate()
                st.session_state.confirm_clear = False
                st.rerun()
            else:
                st.session_state.confirm_clear = True
                st.warning("Click again to confirm.")


# ─── ANALYSIS TRIGGER ─────────────────────────────────────────────────────────
if sidebar_tab == "New Entry" and analyze_btn and input_text.strip():
    raw_input = input_text.strip()
    detected = detect_input_type(raw_input) if source_override == "Auto-detect" else source_override.lower()

    content = raw_input
    fetch_notice = None

    if re.match(r"https?://", raw_input):
        with st.spinner("Fetching " + raw_input[:60] + "..."):
            content = fetch_url_content(raw_input)
            if content.startswith("[Could not"):
                st.error(content)
                st.stop()
            fetch_notice = f"Fetched {len(content)} chars from URL"
            # Auto-detect tickers from URL content
            detected_tickers = extract_tickers(content)
            if detected_tickers:
                fetch_notice += f" · detected ${', '.join(detected_tickers[:3])}"

    with st.spinner(f"Analyzing via {provider}..."):
        try:
            result = analyze_content(content, detected, provider, tier_override)
            # If no tickers in analysis, try to extract them
            if not result.get("tickers"):
                result["tickers"] = extract_tickers(content)[:5]

            entry = {
                "id": str(int(time.time() * 1000)),
                "created_at": datetime.now().isoformat(),
                "raw_url": raw_input if re.match(r"https?://", raw_input) else None,
                "source_type": detected,
                **result,
            }
            saved_id = save_entry(entry)

            # Generate strategies if enabled
            strategies = []
            if gen_strategies:
                with st.spinner("Generating trading strategies..."):
                    portfolio_context = build_portfolio_context()
                    strategies = create_strategies(entry, portfolio_context, provider)

            if fetch_notice:
                st.toast(fetch_notice, icon="✅")
            msg = "Entry added"
            if strategies:
                msg += f" · {len(strategies)} strategy/ies generated"
            st.toast(msg, icon="📊")
            st.rerun()
        except Exception as e:
            st.error("Analysis failed: " + str(e))


# ─── MAIN CONTENT ─────────────────────────────────────────────────────────────

# Category legend
legend_html = ""
for cat, label in CAT_LABELS.items():
    color = CAT_COLORS.get(cat, "#888")
    legend_html += f'<span class="tag" style="color:{color};border-color:{color}33;background:rgba(0,0,0,0.2)">{label}</span> '
st.markdown(f'<div style="margin-bottom:10px">{legend_html}</div>', unsafe_allow_html=True)

if view_mode == "📰 Feed":
    # ─── FEED VIEW ──────────────────────────────────────────────────────────────
    entries = load_entries()

    if cat_filter:
        entries = [e for e in entries if e.get("category") in cat_filter]
    if search_query:
        q = search_query.lower()
        entries = [e for e in entries if
                   q in e.get("title", "").lower() or
                   q in e.get("summary", "").lower() or
                   q in e.get("verdict", "").lower() or
                   any(q in t.lower() for t in e.get("tags", [])) or
                   any(q in t.lower() for t in e.get("tickers", []))]

    all_entries = load_entries()

    # Metric columns
    cat_counts = {}
    for e in all_entries:
        cat = e.get("category", "none") or "none"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    metric_categories = [c for c in CAT_LABELS if cat_counts.get(c, 0) > 0]
    cols = st.columns(1 + len(metric_categories))
    with cols[0]:
        st.metric("📊 Total Signals", len(all_entries))
    for i, cat in enumerate(metric_categories):
        with cols[i + 1]:
            st.metric(CAT_LABELS[cat], cat_counts.get(cat, 0))

    st.divider()

    feed_col = st.container()
    with feed_col:
        st.markdown(f"**Financial Intelligence Feed** — {len(entries)} entry/ies")

        if not entries:
            st.info("Feed is empty. Paste a financial article or URL in the sidebar and hit Analyze.")
        else:
            for entry in entries:
                st.markdown(render_analysis_card(entry), unsafe_allow_html=True)

                # Show associated strategies for this entry
                entry_id = entry.get("id", "")
                strats = load_strategies(entry_id=entry_id)
                if strats:
                    with st.expander(f"📈 Trading Strategies ({len(strats)})", expanded=len(strats) > 0):
                        for s in strats:
                            st.markdown(render_strategy_card(s), unsafe_allow_html=True)
                            # Strategy status controls
                            sid = s.get("id", "")
                            status = s.get("status", "active")
                            cols_s = st.columns([1, 1, 1, 1, 2])
                            if status in ("active", "monitoring") and cols_s[0].button("🎯 Enter", key=f"enter_{sid}"):
                                update_strategy_status(sid, "entered")
                                st.rerun()
                            if status == "entered" and cols_s[0].button("✅ Close Win", key=f"win_{sid}"):
                                update_strategy_status(sid, "closed_win")
                                st.rerun()
                            if status == "entered" and cols_s[1].button("❌ Close Loss", key=f"loss_{sid}"):
                                update_strategy_status(sid, "closed_loss")
                                st.rerun()
                            if status in ("active", "entered") and cols_s[2].button("👀 Monitor", key=f"mon_{sid}"):
                                update_strategy_status(sid, "monitoring")
                                st.rerun()
                            if status == "active" and cols_s[3].button("🗑️ Cancel", key=f"cancel_{sid}"):
                                update_strategy_status(sid, "cancelled")
                                st.rerun()

                doc_id = entry.doc_id
                strategy_col, delete_col = st.columns([5, 1])
                if delete_col.button("🗑️ Delete", key="del_" + str(doc_id), help="Remove this entry"):
                    delete_entry(doc_id)
                    st.rerun()

                st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

elif view_mode == "📊 Strategies":
    # ─── STRATEGIES VIEW ────────────────────────────────────────────────────────

    stats = get_strategy_stats()

    # Metric row
    mcols = st.columns(6)
    mcols[0].metric("📊 Total Strategies", stats.get("total", 0))
    mcols[1].metric("🟡 Active", stats.get("active", 0))
    mcols[2].metric("📌 Entered", stats.get("entered", 0))
    mcols[3].metric("✅ Wins", stats.get("closed_win", 0))
    mcols[4].metric("❌ Losses", stats.get("closed_loss", 0))
    win_rate = stats.get("win_rate", 0)
    wr_color = "normal" if win_rate >= 50 else "inverse"
    mcols[5].metric("🏆 Win Rate", f"{win_rate}%", delta_color=wr_color)

    st.divider()

    # Filters
    col1, col2, col3 = st.columns(3)
    status_filter = col1.selectbox("Status", ["All", "active", "entered", "closed_win", "closed_loss", "monitoring", "cancelled", "expired"])
    risk_filter_val = col2.selectbox("Risk", ["All", "low", "medium", "high"])
    ticker_filter = col3.text_input("Ticker filter", placeholder="$AAPL")

    st.divider()

    strats_all = load_strategies()
    if status_filter != "All":
        strats_all = [s for s in strats_all if s.get("status") == status_filter]
    if risk_filter_val != "All":
        strats_all = [s for s in strats_all if s.get("risk_level") == risk_filter_val]
    if ticker_filter:
        tf = ticker_filter.upper().replace("$", "")
        strats_all = [s for s in strats_all if s.get("ticker", "").upper() == tf]

    if not strats_all:
        st.info("No strategies yet. Analyze financial news to generate trading strategies.")

    for s in strats_all:
        st.markdown(render_strategy_card(s), unsafe_allow_html=True)

        # Status management
        sid = s.get("id", "")
        status = s.get("status", "active")
        with st.expander("Manage", expanded=False):
            row1 = st.columns(5)
            if status in ("active", "monitoring") and row1[0].button("🎯 Mark Entered", key=f"st_enter_{sid}"):
                entry_price = st.session_state.get(f"ep_{sid}")
                update_strategy_status(sid, "entered", entry_price=entry_price)
                st.rerun()
            if status == "entered":
                if row1[1].button("✅ Win", key=f"st_win_{sid}"):
                    exit_price = st.session_state.get(f"xp_{sid}")
                    update_strategy_status(sid, "closed_win", exit_price=exit_price)
                    st.rerun()
                if row1[2].button("❌ Loss", key=f"st_loss_{sid}"):
                    exit_price = st.session_state.get(f"xp_{sid}")
                    update_strategy_status(sid, "closed_loss", exit_price=exit_price)
                    st.rerun()
                if row1[3].button("👀 Monitor", key=f"st_mon_{sid}"):
                    update_strategy_status(sid, "monitoring")
                    st.rerun()
            if row1[4].button("🗑️ Delete", key=f"st_del_{sid}"):
                delete_strategy(sid)
                st.rerun()

            # Entry/Exit price inputs
            row2 = st.columns(2)
            ep = row2[0].number_input("Entry Price", value=0.0, format="%.2f", key=f"ep_{sid}")
            xp = row2[1].number_input("Exit Price", value=0.0, format="%.2f", key=f"xp_{sid}")
