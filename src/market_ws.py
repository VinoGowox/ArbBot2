from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Dict, List

import websockets

logger = logging.getLogger(__name__)


class BinanceBookTickerStream:
    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols
        self._data: Dict[str, Dict[str, float | int]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def get(self, symbol: str) -> Dict[str, float | int] | None:
        with self._lock:
            row = self._data.get(symbol)
            if row is None:
                return None
            return dict(row)

    def _run_loop(self) -> None:
        try:
            asyncio.run(self._consume())
        except Exception as exc:
            logger.warning("Binance WS loop stopped: %s", exc)

    async def _consume(self) -> None:
        streams = []
        for symbol in self.symbols:
            stream_symbol = symbol.replace("/", "").lower()
            streams.append(f"{stream_symbol}@bookTicker")

        if not streams:
            return

        url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Binance WS connected for %d symbols", len(streams))
                    while not self._stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        payload = json.loads(raw)
                        data = payload.get("data", {})
                        symbol_raw = str(data.get("s") or "").upper()
                        if not symbol_raw:
                            continue

                        symbol = f"{symbol_raw[:-4]}/USDT" if symbol_raw.endswith("USDT") else symbol_raw
                        bid = float(data.get("b") or 0.0)
                        ask = float(data.get("a") or 0.0)
                        if bid <= 0 or ask <= 0:
                            continue

                        ts = int(data.get("E") or int(time.time() * 1000))
                        with self._lock:
                            self._data[symbol] = {
                                "bid": bid,
                                "ask": ask,
                                "timestamp_ms": ts,
                            }
            except Exception as exc:
                logger.debug("Binance WS reconnecting after error: %s", exc)
                await asyncio.sleep(2)


class BybitTickerStream:
    def __init__(self, symbols: List[str]) -> None:
        self.symbols = symbols
        self._data: Dict[str, Dict[str, float | int]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def get(self, symbol: str) -> Dict[str, float | int] | None:
        with self._lock:
            row = self._data.get(symbol)
            if row is None:
                return None
            return dict(row)

    def _run_loop(self) -> None:
        try:
            asyncio.run(self._consume())
        except Exception as exc:
            logger.warning("Bybit WS loop stopped: %s", exc)

    async def _consume(self) -> None:
        topics = []
        for symbol in self.symbols:
            symbol_raw = symbol.replace("/", "").upper()
            topics.append(f"orderbook.1.{symbol_raw}")

        if not topics:
            return

        url = "wss://stream.bybit.com/v5/public/spot"
        subscribe_payload = {"op": "subscribe", "args": topics}

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps(subscribe_payload))
                    logger.info("Bybit WS connected for %d symbols", len(topics))

                    while not self._stop_event.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=40)
                        payload = json.loads(raw)

                        topic = str(payload.get("topic") or "")
                        data = payload.get("data")
                        if not topic.startswith("orderbook.") or data is None:
                            continue

                        if not isinstance(data, dict):
                            continue

                        symbol_raw = str(data.get("s") or topic.split(".")[-1]).upper()
                        if not symbol_raw:
                            continue

                        symbol = _to_slash_symbol(symbol_raw)
                        bids = data.get("b") or []
                        asks = data.get("a") or []
                        if not bids or not asks:
                            continue

                        top_bid = bids[0] if isinstance(bids[0], list) else []
                        top_ask = asks[0] if isinstance(asks[0], list) else []
                        if len(top_bid) < 1 or len(top_ask) < 1:
                            continue

                        bid = float(top_bid[0] or 0.0)
                        ask = float(top_ask[0] or 0.0)
                        if bid <= 0 or ask <= 0:
                            continue

                        ts = int(data.get("ts") or payload.get("ts") or int(time.time() * 1000))
                        with self._lock:
                            self._data[symbol] = {
                                "bid": bid,
                                "ask": ask,
                                "timestamp_ms": ts,
                            }
            except Exception as exc:
                logger.debug("Bybit WS reconnecting after error: %s", exc)
                await asyncio.sleep(2)


def _to_slash_symbol(raw: str) -> str:
    raw = raw.upper()
    quote_candidates = ["USDT", "USDC", "BTC", "ETH", "EUR", "USD"]
    for quote in quote_candidates:
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            return f"{base}/{quote}"
    return raw
