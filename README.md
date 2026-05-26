# SIGNAL — Tech Intelligence Digest

A personal tech intelligence dashboard. Paste articles, URLs, Instagram posts, tweets, or notes — SIGNAL fetches the content, analyzes it via LLM, and produces structured intelligence reports with categories, verdicts, and actionable next steps.

Built with Streamlit, Ollama, and friends.

## Features

- **Multi-source ingestion** — URLs, Instagram (with reel audio transcription via Whisper), tweets, newsletters, notes
- **Multi-model analysis** — Ollama (local) or OpenAI-compatible API (OpenCode Zen, etc.)
- **Model tiers** — Light (fast), Default (balanced), Deep (heavy reasoning) — auto-routed by content type
- **Auto-fallback** — if primary provider fails, seamlessly falls back to the other
- **GitHub repo enrichment** — auto-detects repos in content and fetches metadata (stars, topics, license)
- **6-category classification** — Viable, Work, Vaporware, Redundant, Watch, Mixed — with confidence scoring
- **Export** — Markdown or JSON for sharing
- **MCP server** — exposes the intelligence database as MCP tools for Hermes Agent, OpenCode, Claude Code, etc.
- **Password auth** — SHA256-gated access
- **Dark cyberpunk UI** — green-on-black Syne + DM Mono aesthetic

## Requirements

- **Python 3.10+**
- **Ollama** — with at least one model pulled (default: `qwen3:14b`)
- **Optional:** OpenAI-compatible API key for remote model support

## Quick Start

```bash
# Clone / enter the project
cd signal

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
| `SIGNAL_API_PROVIDER` | `ollama` | Default provider: `ollama` or `openai` |
| `SIGNAL_OPENAI_BASE_URL` | `https://opencode.ai/zen/v1` | OpenAI-compatible API endpoint |
| `SIGNAL_OPENAI_API_KEY` | — | API key for OpenAI-compatible provider |
| `SIGNAL_OPENAI_MODEL` | `deepseek-v4-flash-free` | Model name for OpenAI provider |
| `SIGNAL_FALLBACK_ENABLED` | `true` | Auto-fallback between providers on failure |

## Model Configuration

Configure model tiers in `app.py` under `MODEL_TIERS`:

```python
MODEL_TIERS = {
    "light":   {"ollama": "qwen3:latest",       "openai": "deepseek-v4-flash-free"},
    "default": {"ollama": "qwen3:14b",          "openai": "deepseek-v4-flash-free"},
    "deep":    {"ollama": "deepseek-r1:14b",    "openai": "nemotron-3-super-free"},
}
```

Content-type routing (tweet/instagram → light, article/url → default) is in `SOURCE_TIER`.

## MCP Server

SIGNAL ships with an MCP server that exposes its database as tools for any MCP client (Hermes Agent, OpenCode, Claude Code, etc.).

### Standalone

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
  signal:
    command: "/path/to/signal/venv/bin/python"
    args: ["/path/to/signal/mcp_server.py"]
    timeout: 30
```

Available tools (prefixed `mcp_signal_`):
- `signal_list_entries` — list with optional category filter
- `signal_search_entries` — keyword search across titles, summaries, verdicts
- `signal_get_entry` — full entry by ID
- `signal_get_stats` — feed statistics (category breakdown, top tags)
- `signal_export` — export as JSON or Markdown

### Resources
- `signal://entries` — all entries
- `signal://stats` — feed statistics

## Systemd Service

```bash
sudo cp signal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signal
sudo systemctl start signal
```

Runs on port 5757 by default.

## Project Structure

```
signal/
├── app.py            # Main Streamlit application
├── mcp_server.py     # MCP server for external tool integration
├── requirements.txt  # Python dependencies
├── signal.service    # Systemd unit file
├── .streamlit/
│   └── config.toml   # Streamlit theme & server config
├── data/
│   ├── signal.json   # TinyDB database (entries)
│   └── .password_hash # Auth hash (auto-created)
└── venv/             # Virtual environment
```
