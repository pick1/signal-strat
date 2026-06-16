# 📈 TRADING SIGNALS — Financial Intelligence & Strategy Dashboard

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40-FF4B4B?logo=streamlit&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-local-000?logo=ollama&logoColor=white)
![OpenCode Zen](https://img.shields.io/badge/OpenCode_Zen-remote-00BFA5)
![TinyDB](https://img.shields.io/badge/TinyDB-database-FFA000)
![MCP](https://img.shields.io/badge/MCP-server-7B68EE)
![License](https://img.shields.io/badge/license-MIT-808080)

> **Forked from [SIGNAL — Tech Intelligence Digest](https://github.com/pick1/signal_tech_news)**. Retooled for financial news analysis and automated trading strategy generation.

Paste financial articles, earnings reports, SEC filings, or market news URLs — TRADING SIGNALS analyzes them via LLM and generates actionable trading strategies calibrated to your Robinhood portfolio, risk profile, and trading style.

## Features

- **Financial news ingestion** — Paste URLs or article text from Yahoo Finance, Seeking Alpha, Bloomberg, Reuters, CNBC, SEC EDGAR, and more
- **LLM-powered analysis** — Classifies content as Bullish, Bearish, Neutral, Catalyst, Swing, Macro, or Earnings Play with structured analysis
- **Ticker extraction** — Auto-detects stock ticker symbols from article content
- **Trading strategy generation** — Produces 1-3 actionable strategies per analysis with entry conditions, stop loss, take profit, time horizon, and position sizing
- **Portfolio context** — Configure your current holdings, watchlist, risk tolerance, and account size for personalized strategies
- **Strategy tracking** — Track entries, exits, and P&L for each strategy; monitor win rate
- **Multi-model support** — Ollama (local) or OpenAI-compatible API (OpenCode Zen, etc.)
- **Auto-fallback** — Seamlessly falls back between providers
- **MCP server** — Exposes the analysis and strategy database for Hermes Agent, OpenCode, Claude Code
- **Export** — Markdown or JSON for sharing
- **Password auth** — SHA256-gated access
- **Dark cyberpunk UI** — Green-on-black Syne + DM Mono aesthetic

## Requirements

- **Python 3.10+**
- **Ollama** — with at least one model pulled (default: `qwen3:14b`)
- **Optional:** OpenAI-compatible API key for remote model support (OpenCode Zen, etc.)

## Quick Start

```bash
# Clone
git clone https://github.com/pick1/trading-signals.git
cd trading-signals

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

Open http://localhost:5757 — set a password on first launch.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_API_PROVIDER` | `ollama` | Default provider: `ollama` or `openai` |
| `TRADING_OPENAI_BASE_URL` | `https://opencode.ai/zen/v1` | OpenAI-compatible API endpoint |
| `TRADING_OPENAI_API_KEY` | — | API key for OpenAI-compatible provider |
| `TRADING_OPENAI_MODEL` | `deepseek-v4-flash-free` | Model name for OpenAI provider |
| `TRADING_FALLBACK_ENABLED` | `true` | Auto-fallback between providers on failure |
| `ROBINHOOD_USERNAME` | — | Robinhood username (optional, for context) |
| `ROBINHOOD_PASSWORD` | — | Robinhood password (optional) |

## Model Configuration

Configure model tiers in `trading_signals/config.py` under `MODEL_TIERS`:

```python
MODEL_TIERS = {
    "light":   {"ollama": "qwen3:latest",       "openai": "deepseek-v4-flash-free"},
    "default": {"ollama": "gemma4:e4b",         "openai": "deepseek-v4-flash-free"},
    "deep":    {"ollama": "deepseek-r1:14b",    "openai": "nemotron-3-super-free"},
}
```

## How It Works

1. **Paste content** — A financial article URL or raw text
2. **Fetch & extract** — Content is scraped (trafilatura + BS4), tickers auto-detected
3. **LLM Analysis** — The content is analyzed with a financial analyst system prompt, producing category, verdict, market impact, key metrics
4. **Strategy Generation** — A second LLM call generates 1-3 trading strategies calibrated to your portfolio context
5. **Track** — Monitor strategy status, log entries/exits, track P&L

### Analysis Categories

| Category | Description |
|----------|-------------|
| 🟢 **Bullish** | Positive sentiment — stock likely to appreciate |
| 🔴 **Bearish** | Negative sentiment — stock likely to decline |
| ⚪ **Neutral** | Balanced or uncertain |
| 🟣 **Catalyst** | Upcoming event could move the stock |
| 🔵 **Swing** | Short-to-medium term momentum play |
| 🟡 **Macro** | Macroeconomic trend affecting multiple sectors |
| 🔵 **Earnings** | Pre/post earnings report analysis |

## MCP Server

```bash
# stdio transport (for Hermes/OpenCode integration)
python mcp_server.py

# HTTP/SSE transport (for remote clients)
python mcp_server.py --transport sse --port 8765
```

### Hermes Agent Integration

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  trading-signals:
    command: "/path/to/trading-signals/venv/bin/python"
    args: ["/path/to/trading-signals/mcp_server.py"]
    timeout: 30
```

Available tools (prefixed `ts_`):
- `ts_list_entries` — list with optional category filter
- `ts_search_entries` — keyword search across titles, summaries, verdicts, tickers
- `ts_get_entry` — full entry by ID
- `ts_get_stats` — feed statistics (category breakdown, top tickers)
- `ts_list_strategies` — list trading strategies with optional filters
- `ts_get_strategy_stats` — aggregate strategy performance
- `ts_analyze_and_generate` — end-to-end: analyze content + generate strategies

### Resources
- `trading-signals://entries` — all entries
- `trading-signals://stats` — feed statistics
- `trading-signals://strategies` — all strategies

## Systemd Service

```bash
sudo cp trading-signals.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trading-signals
sudo systemctl start trading-signals
```

Runs on port 5757 by default.

## Portfolio Management

Configure your trading context in the **Portfolio** and **Risk Profile** sidebar tabs:
- Add current holdings (ticker, shares, average cost)
- Build a watchlist
- Set risk tolerance (conservative/moderate/aggressive)
- Configure account value and max position size
- Set trading style and experience level

Strategy generation automatically uses this context to produce relevant, appropriately-sized recommendations.

## Project Structure

```
trading-signals/
├── app.py                          # Main Streamlit application
├── mcp_server.py                   # MCP server for external tool integration
├── requirements.txt                # Python dependencies
├── trading-signals.service         # Systemd unit file
├── .streamlit/
│   └── config.toml                 # Streamlit theme & server config
├── data/
│   ├── trading_signals.json        # TinyDB database (analysis entries)
│   ├── strategies.json             # TinyDB database (trading strategies)
│   ├── portfolio.json              # TinyDB database (portfolio context)
│   └── .password_hash              # Auth hash (auto-created)
├── trading_signals/                # Package
│   ├── __init__.py
│   ├── config.py                   # Configuration, categories, prompts
│   ├── analyzer.py                 # LLM analysis + strategy generation
│   ├── db.py                       # TinyDB operations
│   ├── scrapers.py                 # Content fetching (no Instagram/Whisper)
│   ├── strategy_engine.py          # Strategy lifecycle management
│   ├── portfolio.py                # Portfolio & risk profile management
│   └── auth.py                     # Password authentication
└── venv/                           # Virtual environment
```

## License

MIT — Forked from [SIGNAL](https://github.com/pick1/signal_tech_news).

## Disclaimer

**For educational and research purposes only.** This tool generates trading strategy suggestions based on LLM analysis of financial news. It does not constitute financial advice. Always do your own research before making trading decisions. Past performance does not guarantee future results.
