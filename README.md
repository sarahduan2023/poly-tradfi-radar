# ⚡ Poly x TradFi Macro Divergence Radar

[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Polymarket CLOB](https://img.shields.io/badge/Polymarket-CLOB%20Level--0-purple.svg)](https://github.com/Polymarket/py-clob-client)
[![Market Data: yfinance](https://img.shields.io/badge/TradFi-Yahoo%20Finance-green.svg)](https://github.com/ranaroussi/yfinance)

> **Real-time cross-market quantitative radar detecting macro regime dislocations between Web3 prediction markets (Polymarket CLOB) and Traditional Finance assets (Nasdaq-100 ETF `QQQ` & 10Y US Treasury Yield `^TNX`).**

---

## 🧭 The Core Thesis & Quant Rationale

In modern macro trading, **information diffusion is asymmetric**:
1. **Decentralized Prediction Markets (Polymarket)** often react instantly to political events, Fed rhetoric leaks, geopolitical developments, and retail/smart-money consensus. Probabilities derived from the Central Limit Order Book (CLOB) represent an unfiltered, capital-weighted distribution of macro outcomes.
2. **Traditional Equity & Rates Markets (`QQQ` / `^TNX`)** are heavily anchored by institutional algorithmic execution, options gamma pin-risk, and structural liquidity flows.

When probability shifts rapidly on prediction markets while underlying TradFi benchmarks decouple or move inversely, a **Macro Divergence Regime** occurs. This monitor isolates those dislocations in real-time, giving quantitative traders an early edge before cross-asset repricing converges.

```
                    ┌──────────────────────────────────────────────┐
                    │       Polymarket CLOB / Gamma Events         │
                    │   (Fast-Moving Real-Money Macro Consensus)   │
                    └──────────────────────┬───────────────────────┘
                                           │ Δ Prob (Odds Shift)
                                           ▼
┌────────────────────────┐      ┌─────────────────────┐      ┌────────────────────────┐
│ TradFi Equities: QQQ   ├─────►│  DIVERGENCE ENGINE  │◄─────┤ TradFi Rates: ^TNX     │
│ (Institutional Flows)  │      │  Rolling Window Δ%  │      │ (10Y Benchmark Yield)  │
└────────────────────────┘      └──────────┬──────────┘      └────────────────────────┘
                                           │
                                  [Spread Filter Safe]
                                           │
                                           ▼
                        🚨 Real-Time Discord / Telegram Alerts
```

---

## ⚡ Detection Regimes & Microstructure Filters

### 1. Macro Divergence Regimes
The engine tracks a FIFO rolling window of snapshots and evaluates the differential between baseline and current state:

- **`BEARISH_EQUITY_DIVERGENCE` (Rate-cut odds surge vs. Equity sell-off)**
  - $\Delta \text{Prob} \ge +\text{PROB\_DELTA\_THRESHOLD}$ (e.g., $+1.5\%$)
  - $\Delta \text{QQQ} \le -\text{EQUITY\_PCT\_THRESHOLD}$ (e.g., $-0.25\%$)
  - *Quant Interpretation*: Market is pricing in panic or recessionary cuts; equities decouple downward despite easing expectations.

- **`HAWKISH_ODDS_DIVERGENCE` (Equity rally vs. Rate-cut odds slump)**
  - $\Delta \text{Prob} \le -\text{PROB\_DELTA\_THRESHOLD}$ (e.g., $-1.5\%$)
  - $\Delta \text{QQQ} \ge +\text{EQUITY\_PCT\_THRESHOLD}$ (e.g., $+0.25\%$)
  - *Quant Interpretation*: Speculative equity squeeze unbacked by rate support; high vulnerability to sudden mean-reversion.

### 2. Orderbook Depth & Spread Wick Protection
In crypto prediction order books, wide bid-ask spreads or illiquid market-taker sweeps can produce artificial price "wicks" that do not reflect genuine consensus shifts.

```
Ask: $0.65 ──┐  Spread = $0.10 (10¢) > MAX_SPREAD_THRESHOLD (3¢)
             ├──► ⚠️  SKIPPED (Illiquid Wick Protection Triggered)
Bid: $0.55 ──┘
```

- **`MAX_SPREAD_THRESHOLD`**: Defaults to `$0.03` (3¢).
- If $\text{BestAsk} - \text{BestBid} > \text{Threshold}$, divergence evaluation is suspended for that tick, eliminating false-positive alerts.

---

## 🛠️ Architecture & Pipeline

```
  ┌──────────────────┐               ┌──────────────────┐
  │ Polymarket CLOB  │               │   Yahoo Finance  │
  │ /midpoint, /book │               │   QQQ and ^TNX   │
  └────────┬─────────┘               └────────┬─────────┘
           │                                  │
           └─────────────────┬────────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │  MarketSnapshot Ingestion   │
              │  (Prob, Spread, QQQ, ^TNX)  │
              └──────────────┬──────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │ Rolling Window Queue (N=15) │
              └──────────────┬──────────────┘
                             │
            ┌────────────────┴────────────────┐
            │ Spread > MAX_SPREAD_THRESHOLD?  │
            └──┬───────────────────────────┬──┘
              YES                          NO
               │                           │
               ▼                           ▼
        [Skip Evaluation]         ┌───────────────────┐
        (Log liquidity warning)   │ Divergence Engine │
                                  └─────────┬─────────┘
                                            │
                                   Trigger Matched?
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │ Dispatch Webhook     │
                                │ (Telegram / Discord) │
                                └──────────────────────┘
```

---

## 🚀 Quickstart (macOS / Linux)

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/your-username/poly-tradfi-radar.git
cd poly-tradfi-radar

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example configuration:
```bash
cp .env.example .env
```

Edit `.env` to configure your target Polymarket token, alert thresholds, and notification webhooks:
```ini
# Target Polymarket Token
POLY_TOKEN_ID=113379839734351069617987084078322474966003108854908079701423911002443710490196
POLY_EVENT_LABEL="Will 1 Fed rate cut happen in 2026 (Yes)"

# TradFi Symbols
EQUITY_TICKER=QQQ
YIELD_TICKER=^TNX

# Thresholds
PROB_DELTA_THRESHOLD=0.015
EQUITY_PCT_THRESHOLD=0.25
MAX_SPREAD_THRESHOLD=0.03
POLL_INTERVAL_SEC=60

# Telegram Webhook
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Local Proxy (Optional, for regions requiring proxy access)
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
```

---

## 💻 CLI Commands & Usage

### 1. Discover Active Macro Token IDs
Queries the Polymarket Gamma API to search for active Fed / macro contracts and displays their corresponding `Yes` / `No` Token IDs:

```bash
.venv/bin/python poly_tradfi_monitor.py --discover "Fed"
```

*Example Output:*
```text
[Event] How many Fed rate cuts in 2026? (Slug: how-many-fed-rate-cuts-in-2026)
  └── Market: Will 1 Fed rate cut happen in 2026?
        • Yes  Token ID: 113379839734351069617987084078322474966003108854908079701423911002443710490196
        • No   Token ID: 48058805012599375970268777474956242772204241523361869981040579395242001094965
```

### 2. Test Alert Webhooks in Mock Mode
Generates synthetic price steps to trigger divergence detection and verify Discord/Telegram webhook delivery:

```bash
.venv/bin/python poly_tradfi_monitor.py --mock --ticks 3
```

*Example Output:*
```text
16:10:40 | INFO    | Starting Poly x TradFi Monitor | Event='Will 1 Fed rate cut happen in 2026 (Yes)' | TradFi=QQQ/^TNX | Window=15 ticks
16:10:40 | INFO    | Tick #01 | Poly= 60.2% (Spread 1.0¢) | QQQ=$499.96 | ^TNX=4.12%
16:10:41 | INFO    | Tick #02 | Poly= 63.3% (Spread 1.0¢) | QQQ=$497.02 | ^TNX=4.16%
16:10:41 | WARNING | TRIGGERED ALERT ->
🚨 **[Macro Divergence Alert]** `BEARISH_EQUITY_DIVERGENCE (降息预期跳升 vs 纳指背离下跌)`
• **Polymarket (Will 1 Fed rate cut happen in 2026 (Yes))**: `63.3%` (`+3.16%` | Spread `1.0¢`)
• **TradFi (QQQ)**: `$497.02` (`-0.59%`)
• **10Y Yield (^TNX)**: `4.16%` (`+4.0 bps`)
16:10:42 | INFO    | Telegram alert delivered.
```

### 3. Run a Live Real-Time Snapshot
Fetches live Level-0 CLOB orderbook prices and Yahoo Finance quotes, sends an online confirmation card to your Telegram on Tick #1, and exits:

```bash
.venv/bin/python poly_tradfi_monitor.py --once
```

### 4. 7x24 Daemon Mode
Runs continuous monitoring with custom poll intervals and symbol pairs:

```bash
# Monitor QQQ and 10Y Yield with 30s frequency
.venv/bin/python poly_tradfi_monitor.py --interval 30 --tickers "QQQ,^TNX"
```

---

## ⚙️ Configuration Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `POLY_CLOB_HOST` | `https://clob.polymarket.com` | Polymarket CLOB production endpoint |
| `POLY_TOKEN_ID` | *(Fed Token ID)* | Target prediction market outcome token ID |
| `POLY_EVENT_LABEL` | `"Will 1 Fed rate cut..."` | Descriptive label displayed in notifications |
| `EQUITY_TICKER` | `QQQ` | TradFi Equity ETF benchmark (e.g., `QQQ`, `SPY`) |
| `YIELD_TICKER` | `^TNX` | TradFi Rates benchmark (e.g., `^TNX`, `^TYX`) |
| `WINDOW_SIZE` | `15` | Rolling snapshot history depth |
| `POLL_INTERVAL_SEC` | `60` | Polling frequency in seconds |
| `PROB_DELTA_THRESHOLD`| `0.015` | Minimum probability move to trigger divergence (1.5%) |
| `EQUITY_PCT_THRESHOLD`| `0.25` | Minimum equity move to trigger divergence (0.25%) |
| `MAX_SPREAD_THRESHOLD`| `0.03` | Max bid-ask spread permitted (3¢) before skipping |
| `ALERT_COOLDOWN_SEC` | `900` | Cooldown period between duplicate alerts (15 min) |
| `DISCORD_WEBHOOK_URL`| *(empty)* | Discord webhook URL for alert embeds |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Telegram Bot API token |
| `TELEGRAM_CHAT_ID`   | *(empty)* | Target Telegram Chat / User ID |

---

## 📄 License

Distributed under the [MIT License](LICENSE).
See `LICENSE` for more information.
