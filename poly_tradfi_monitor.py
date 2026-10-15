#!/usr/bin/env python3
"""
PolyMacro-Divergence-Monitor (poly_tradfi_monitor.py)
=====================================================
A minimalist, hardcore Python monitor that detects real-time macro divergences
between Web3 prediction markets (Polymarket CLOB) and TradFi assets (QQQ / ^TNX).

Docs & References:
- Polymarket CLOB Client: https://github.com/Polymarket/py-clob-client
- Polymarket Unified SDK: https://github.com/Polymarket/py-sdk
- Polymarket Gamma API:   https://docs.polymarket.com/developers/gamma-markets-api/get-markets
- yfinance Library:       https://github.com/ranaroussi/yfinance
- Discord Webhooks:       https://docs.discord.com/developers/resources/webhook
- Telegram Bot API:       https://core.telegram.org/bots/api#sendmessage
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import random
import time
from typing import Deque, Dict, Optional, Tuple
import requests

# Auto-load .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Optional imports with graceful fallback for --discover / --mock modes
try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None  # type: ignore

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore


# ============================================================================
# 1. CONFIGURATION (Override via .env or CLI flags)
# ============================================================================
CLOB_HOST = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
GAMMA_API_URL = "https://gamma-api.polymarket.com/events"

# Target Polymarket Outcome Token ID (Use `--discover "Fed"` to find active IDs)
POLY_TOKEN_ID = os.getenv(
    "POLY_TOKEN_ID",
    "21742633143463906290569050155826241533067272736897614950488156847949938836455",
)
EVENT_LABEL = os.getenv("POLY_EVENT_LABEL", "Fed Rate Cut (Yes)")

# TradFi Symbols via Yahoo Finance
EQUITY_TICKER = os.getenv("EQUITY_TICKER", "QQQ")     # Nasdaq-100 ETF
YIELD_TICKER = os.getenv("YIELD_TICKER", "^TNX")      # 10-Year US Treasury Yield

# Divergence Thresholds (Rolling Window comparison between oldest & newest snapshot)
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "15"))     # Keep last 15 snapshots
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "60"))
PROB_DELTA_THRESHOLD = float(os.getenv("PROB_DELTA_THRESHOLD", "0.025"))   # 2.5% prob shift
EQUITY_PCT_THRESHOLD = float(os.getenv("EQUITY_PCT_THRESHOLD", "0.35"))    # 0.35% QQQ move
MAX_SPREAD_THRESHOLD = float(os.getenv("MAX_SPREAD_THRESHOLD", "0.03"))    # 3 cents spread threshold
ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", "900"))           # 15 min cooldown

# Webhook Notification Credentials
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PolyTradFi")


# ============================================================================
# 2. DATA MODELS
# ============================================================================
@dataclass
class MarketSnapshot:
    timestamp: datetime
    poly_prob: float        # 0.0 to 1.0 (e.g., 0.645 = 64.5%)
    poly_spread: float      # Best Ask - Best Bid on CLOB
    equity_price: float     # e.g., QQQ price
    yield_10y: float        # e.g., ^TNX yield in %


# ============================================================================
# 3. WEB3 MODULE: POLYMARKET GAMMA DISCOVERY & CLOB CLIENT
# ============================================================================
def discover_macro_tokens(keyword: str = "Fed", limit: int = 10) -> None:
    """Queries Polymarket Gamma API to find active macro markets and CLOB Token IDs."""
    logger.info("Searching Polymarket Gamma API for active events matching '%s'...", keyword)
    matches = 0

    for offset in range(0, 600, 100):
        try:
            resp = requests.get(
                GAMMA_API_URL,
                params={"active": "true", "closed": "false", "limit": 100, "offset": offset},
                timeout=10,
            )
            resp.raise_for_status()
            events = resp.json()
            if not events:
                break
        except Exception as exc:
            logger.error("Failed fetching Gamma events at offset %d: %s", offset, exc)
            break

        for event in events:
            title = event.get("title", "")
            if keyword.lower() not in title.lower():
                continue
            matches += 1
            print(f"\n[Event] {title} (Slug: {event.get('slug')})")
            for mkt in event.get("markets", []):
                if mkt.get("closed") or not mkt.get("clobTokenIds"):
                    continue
                question = mkt.get("question", "")
                raw_tokens = mkt["clobTokenIds"]
                token_ids = json.loads(raw_tokens) if isinstance(raw_tokens, str) else raw_tokens
                raw_outcomes = mkt.get("outcomes", '["Yes", "No"]')
                outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes

                print(f"  └── Market: {question}")
                for outcome, tid in zip(outcomes, token_ids):
                    print(f"        • {outcome:<4} Token ID: {tid}")

            if matches >= limit:
                return

    if matches == 0:
        logger.warning("No active events matched '%s'. Try a broader keyword.", keyword)


class PolymarketCLOBFeed:
    """Fetches real-time order book probability using Level-0 ClobClient with REST fallback."""

    def __init__(self, host: str, token_id: str) -> None:
        self.host = host.rstrip("/")
        self.token_id = token_id
        self.client = ClobClient(self.host) if ClobClient is not None else None

    def fetch_prob_and_spread(self) -> Tuple[float, float]:
        """Returns (midpoint_probability, bid_ask_spread)."""
        # 1. Primary path: Official py_clob_client (Level-0 read-only, no private key needed)
        if self.client is not None:
            try:
                mid_resp = self.client.get_midpoint(self.token_id)
                buy_resp = self.client.get_price(self.token_id, side="BUY")
                sell_resp = self.client.get_price(self.token_id, side="SELL")

                mid = float(mid_resp.get("mid", 0.0)) if isinstance(mid_resp, dict) else float(mid_resp)
                bid = float(buy_resp.get("price", mid)) if isinstance(buy_resp, dict) else mid
                ask = float(sell_resp.get("price", mid)) if isinstance(sell_resp, dict) else mid
                spread = max(0.0, ask - bid)
                if mid > 0:
                    return mid, spread
            except Exception as exc:
                logger.debug("py_clob_client fallback triggered (%s), using CLOB REST.", exc)

        # 2. Fallback path: Direct CLOB V2 REST endpoints
        mid_r = requests.get(
            f"{self.host}/midpoint", params={"token_id": self.token_id}, timeout=8
        ).json()
        book_r = requests.get(
            f"{self.host}/book", params={"token_id": self.token_id}, timeout=8
        ).json()

        mid = float(mid_r.get("mid", 0.0))
        bids = book_r.get("bids", [])
        asks = book_r.get("asks", [])
        best_bid = float(bids[-1]["price"]) if bids else mid
        best_ask = float(asks[-1]["price"]) if asks else mid
        return mid, max(0.0, best_ask - best_bid)


# ============================================================================
# 4. TRADFI MODULE: YFINANCE LIGHTWEIGHT FETCHER
# ============================================================================
class TradFiFeed:
    """Fetches real-time QQQ and 10Y Treasury Yield (^TNX) via yfinance."""

    def __init__(self, equity_ticker: str, yield_ticker: str) -> None:
        self.equity_ticker = equity_ticker
        self.yield_ticker = yield_ticker

    @staticmethod
    def _latest_price(symbol: str) -> float:
        if yf is None:
            raise RuntimeError("yfinance is not installed. Run `pip install yfinance`.")
        ticker = yf.Ticker(symbol)
        price = getattr(ticker.fast_info, "last_price", None)
        if price is not None and price > 0:
            return float(price)
        hist = ticker.history(period="1d", interval="1m")
        if hist.empty:
            raise ValueError(f"No market data returned for {symbol}")
        return float(hist["Close"].iloc[-1])

    def fetch_quotes(self) -> Tuple[float, float]:
        return self._latest_price(self.equity_ticker), self._latest_price(self.yield_ticker)


# ============================================================================
# 5. DIVERGENCE ENGINE & WEBHOOK NOTIFIER (DISCORD / TELEGRAM)
# ============================================================================
def evaluate_divergence(
    history: Deque[MarketSnapshot],
) -> Optional[Tuple[str, Dict[str, float]]]:
    """
    Compares earliest snapshot in rolling window vs. latest snapshot.
    Detects two classic macro divergence regimes:
      1. BEARISH_EQUITY_DIVERGENCE: Rate-cut odds surge (+ΔProb), but QQQ dumps (-ΔQQQ%).
      2. HAWKISH_ODDS_DIVERGENCE:   QQQ rallies (+ΔQQQ%), but Rate-cut odds slump (-ΔProb).
    """
    if len(history) < 2:
        return None

    base = history[0]
    curr = history[-1]

    # Orderbook depth & liquidity protection: skip if spread exceeds MAX_SPREAD_THRESHOLD
    if curr.poly_spread > MAX_SPREAD_THRESHOLD:
        logger.warning(
            "Spread too wide (%.1f¢ > %.1f¢ threshold), skipping divergence evaluation to avoid illiquid wicks.",
            curr.poly_spread * 100.0,
            MAX_SPREAD_THRESHOLD * 100.0,
        )
        return None

    prob_delta = curr.poly_prob - base.poly_prob
    equity_pct = ((curr.equity_price - base.equity_price) / base.equity_price) * 100.0
    yield_bps = (curr.yield_10y - base.yield_10y) * 100.0

    metrics = {
        "prob_curr": curr.poly_prob * 100.0,
        "prob_delta_pct": prob_delta * 100.0,
        "poly_spread_cents": curr.poly_spread * 100.0,
        "equity_curr": curr.equity_price,
        "equity_pct": equity_pct,
        "yield_curr": curr.yield_10y,
        "yield_bps": yield_bps,
    }

    if prob_delta >= PROB_DELTA_THRESHOLD and equity_pct <= -EQUITY_PCT_THRESHOLD:
        return "BEARISH_EQUITY_DIVERGENCE (降息预期跳升 vs 纳指背离下跌)", metrics

    if prob_delta <= -PROB_DELTA_THRESHOLD and equity_pct >= EQUITY_PCT_THRESHOLD:
        return "HAWKISH_ODDS_DIVERGENCE (纳指强势拉升 vs 降息预期跳水)", metrics

    return None


def send_online_alert(
    snap: MarketSnapshot, equity_symbol: str, yield_symbol: str
) -> None:
    """Dispatches a radar online confirmation notification to Telegram and/or Discord."""
    summary_text = (
        f"🟢 **[Poly x TradFi Radar Online]**\n"
        f"• **Target Market**: `{EVENT_LABEL}`\n"
        f"• **Polymarket Odds**: `{snap.poly_prob * 100.0:.1f}%` (Spread `{snap.poly_spread * 100.0:.1f}¢`)\n"
        f"• **TradFi ({equity_symbol})**: `${snap.equity_price:.2f}`\n"
        f"• **10Y Yield ({yield_symbol})**: `{snap.yield_10y:.2f}%`\n"
        f"• **Thresholds**: ΔProb `≥{PROB_DELTA_THRESHOLD * 100.0:.1f}%` | "
        f"Δ{equity_symbol} `≥{EQUITY_PCT_THRESHOLD:.2f}%` | MaxSpread `{MAX_SPREAD_THRESHOLD * 100.0:.0f}¢`"
    )
    logger.info("Radar Online Notification ->\n%s", summary_text)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": summary_text,
            "parse_mode": "Markdown",
        }
        try:
            r = requests.post(tg_url, json=payload, timeout=8)
            r.raise_for_status()
            logger.info("Telegram online confirmation delivered.")
        except Exception as exc:
            logger.error("Telegram online confirmation failed: %s", exc)

    if DISCORD_WEBHOOK_URL:
        payload = {
            "username": "Poly x TradFi Radar",
            "embeds": [
                {
                    "title": "🟢 Poly x TradFi Radar Online",
                    "description": summary_text,
                    "color": 3066993,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=8)
            r.raise_for_status()
            logger.info("Discord online confirmation delivered.")
        except Exception as exc:
            logger.error("Discord online confirmation failed: %s", exc)


def send_webhook_alert(
    signal_type: str, metrics: Dict[str, float], equity_symbol: str, yield_symbol: str
) -> None:
    """Dispatches formatted macro divergence alert to Discord and/or Telegram."""
    summary_text = (
        f"🚨 **[Macro Divergence Alert]** `{signal_type}`\n"
        f"• **Polymarket ({EVENT_LABEL})**: `{metrics['prob_curr']:.1f}%` "
        f"(`{metrics['prob_delta_pct']:+.2f}%` | Spread `{metrics['poly_spread_cents']:.1f}¢`)\n"
        f"• **TradFi ({equity_symbol})**: `${metrics['equity_curr']:.2f}` (`{metrics['equity_pct']:+.2f}%`)\n"
        f"• **10Y Yield ({yield_symbol})**: `{metrics['yield_curr']:.2f}%` (`{metrics['yield_bps']:+.1f} bps`)"
    )
    logger.warning("TRIGGERED ALERT ->\n%s", summary_text)

    if DISCORD_WEBHOOK_URL:
        payload = {
            "username": "Poly x TradFi Radar",
            "embeds": [
                {
                    "title": f"🚨 {signal_type}",
                    "description": summary_text,
                    "color": 16734296,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=8)
            r.raise_for_status()
            logger.info("Discord webhook delivered.")
        except Exception as exc:
            logger.error("Discord webhook failed: %s", exc)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": summary_text,
            "parse_mode": "Markdown",
        }
        try:
            r = requests.post(tg_url, json=payload, timeout=8)
            r.raise_for_status()
            logger.info("Telegram alert delivered.")
        except Exception as exc:
            logger.error("Telegram alert failed: %s", exc)


# ============================================================================
# 6. MAIN EVENT LOOP & CLI ENTRYPOINT
# ============================================================================
def run_monitor(
    mock_mode: bool = False,
    max_ticks: Optional[int] = None,
    interval_sec: int = POLL_INTERVAL_SEC,
    equity_symbol: str = EQUITY_TICKER,
    yield_symbol: str = YIELD_TICKER,
) -> None:
    history: Deque[MarketSnapshot] = deque(maxlen=WINDOW_SIZE)
    poly_feed = PolymarketCLOBFeed(CLOB_HOST, POLY_TOKEN_ID)
    tradfi_feed = TradFiFeed(equity_symbol, yield_symbol)
    last_alert_ts = 0.0
    tick = 0

    logger.info(
        "Starting Poly x TradFi Monitor | Event='%s' | TradFi=%s/%s | Window=%d ticks",
        EVENT_LABEL,
        equity_symbol,
        yield_symbol,
        WINDOW_SIZE,
    )

    while True:
        tick += 1
        try:
            if mock_mode:
                base_prob = 0.600 + (0.032 if tick >= 2 else 0.0) + random.uniform(-0.002, 0.002)
                base_qqq = 500.00 * (0.994 if tick >= 2 else 1.0) + random.uniform(-0.1, 0.1)
                base_tnx = 4.12 + (0.04 if tick >= 2 else 0.0)
                snap = MarketSnapshot(
                    timestamp=datetime.now(timezone.utc),
                    poly_prob=base_prob,
                    poly_spread=0.01,
                    equity_price=base_qqq,
                    yield_10y=base_tnx,
                )
            else:
                prob, spread = poly_feed.fetch_prob_and_spread()
                eq_price, yld_val = tradfi_feed.fetch_quotes()
                snap = MarketSnapshot(
                    timestamp=datetime.now(timezone.utc),
                    poly_prob=prob,
                    poly_spread=spread,
                    equity_price=eq_price,
                    yield_10y=yld_val,
                )

            history.append(snap)
            logger.info(
                "Tick #%02d | Poly=%5.1f%% (Spread %.1f¢) | %s=$%.2f | %s=%.2f%%",
                tick,
                snap.poly_prob * 100.0,
                snap.poly_spread * 100.0,
                equity_symbol,
                snap.equity_price,
                yield_symbol,
                snap.yield_10y,
            )

            # Send online confirmation card on tick #1 in live mode
            if not mock_mode and tick == 1:
                send_online_alert(snap, equity_symbol, yield_symbol)

            result = evaluate_divergence(history)
            now_ts = time.time()
            if result and (now_ts - last_alert_ts >= ALERT_COOLDOWN_SEC or mock_mode):
                signal_type, metrics = result
                send_webhook_alert(signal_type, metrics, equity_symbol, yield_symbol)
                last_alert_ts = now_ts

        except Exception as exc:
            logger.error("Tick #%02d error: %s", tick, exc)

        if max_ticks is not None and tick >= max_ticks:
            logger.info("Reached max_ticks=%d. Exiting cleanly.", max_ticks)
            break

        time.sleep(1 if mock_mode else interval_sec)


def main() -> None:
    global MAX_SPREAD_THRESHOLD
    parser = argparse.ArgumentParser(
        description="Polymarket CLOB x TradFi (QQQ/^TNX) Macro Divergence Monitor"
    )
    parser.add_argument(
        "--discover",
        type=str,
        metavar="KEYWORD",
        help="Search Polymarket Gamma API for active event Token IDs (e.g., --discover 'Fed')",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run with synthetic divergence data to test logic & Discord/Telegram webhooks",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Stop after N ticks (useful for CI/testing)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single snapshot tick and exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL_SEC,
        help="Polling interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated equity and yield tickers (e.g., 'QQQ,^TNX')",
    )
    parser.add_argument(
        "--max-spread",
        type=float,
        default=MAX_SPREAD_THRESHOLD,
        help=f"Max orderbook spread allowed for divergence evaluation (default: {MAX_SPREAD_THRESHOLD})",
    )
    args = parser.parse_args()

    MAX_SPREAD_THRESHOLD = args.max_spread

    equity_sym, yield_sym = EQUITY_TICKER, YIELD_TICKER
    if args.tickers:
        parts = [p.strip() for p in args.tickers.split(",") if p.strip()]
        if len(parts) >= 2:
            equity_sym, yield_sym = parts[0], parts[1]
        elif len(parts) == 1:
            equity_sym = parts[0]

    max_ticks = 1 if args.once else args.ticks

    if args.discover:
        discover_macro_tokens(args.discover)
    else:
        run_monitor(
            mock_mode=args.mock,
            max_ticks=max_ticks,
            interval_sec=args.interval,
            equity_symbol=equity_sym,
            yield_symbol=yield_sym,
        )


if __name__ == "__main__":
    main()
