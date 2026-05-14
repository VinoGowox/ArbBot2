from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import ccxt

from .config import BotConfig
from .models import TickerSnapshot

logger = logging.getLogger(__name__)


class ExchangeGateway:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.clients = self._init_clients(config.exchanges)

    def _init_clients(self, exchanges: List[str]) -> Dict[str, ccxt.Exchange]:
        clients: Dict[str, ccxt.Exchange] = {}
        for exchange_name in exchanges:
            exchange_cls = getattr(ccxt, exchange_name, None)
            if exchange_cls is None:
                logger.warning("Exchange not supported by ccxt: %s", exchange_name)
                continue

            params = {
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }

            api_key = _env_or_empty(f"{exchange_name.upper()}_API_KEY")
            api_secret = _env_or_empty(f"{exchange_name.upper()}_API_SECRET")
            password = _env_or_empty(f"{exchange_name.upper()}_PASSWORD")

            if api_key and api_secret:
                params["apiKey"] = api_key
                params["secret"] = api_secret
                if password:
                    params["password"] = password

            clients[exchange_name] = exchange_cls(params)

        return clients

    def resolve_taker_fees(
        self,
        symbols: List[str],
        fallback: Dict[str, float],
    ) -> Dict[str, float]:
        resolved: Dict[str, float] = {}
        for exchange_name, client in self.clients.items():
            fallback_fee = float(fallback.get(exchange_name, 0.001))
            best_fee = fallback_fee

            markets = None
            try:
                markets = client.load_markets()
            except Exception as exc:
                logger.debug("load_markets failed | %s | %s", exchange_name, exc)

            market_fees: List[float] = []
            if markets:
                for symbol in symbols:
                    market = markets.get(symbol)
                    if not market:
                        continue
                    taker = float(market.get("taker") or 0.0)
                    if taker > 0:
                        market_fees.append(taker)

            api_fees: List[float] = []
            try:
                has_fetch = bool(getattr(client, "has", {}).get("fetchTradingFees"))
                if has_fetch:
                    fee_data = client.fetch_trading_fees()
                    if isinstance(fee_data, dict):
                        for symbol in symbols:
                            row = fee_data.get(symbol)
                            if not isinstance(row, dict):
                                continue
                            taker = float(row.get("taker") or 0.0)
                            if taker > 0:
                                api_fees.append(taker)
            except Exception as exc:
                logger.debug("fetch_trading_fees failed | %s | %s", exchange_name, exc)

            if api_fees:
                best_fee = sum(api_fees) / len(api_fees)
            elif market_fees:
                best_fee = sum(market_fees) / len(market_fees)

            resolved[exchange_name] = best_fee

        for exchange_name in fallback:
            if exchange_name not in resolved:
                resolved[exchange_name] = float(fallback[exchange_name])

        return resolved

    def fetch_all_tickers(self, symbols: List[str]) -> Dict[str, Dict[str, TickerSnapshot]]:
        results: Dict[str, Dict[str, TickerSnapshot]] = {ex: {} for ex in self.clients}

        jobs = []
        with ThreadPoolExecutor(max_workers=max(4, len(self.clients) * len(symbols))) as pool:
            for exchange_name, client in self.clients.items():
                for symbol in symbols:
                    jobs.append(pool.submit(self._fetch_one, exchange_name, client, symbol))

            for future in as_completed(jobs):
                snapshot = future.result()
                if snapshot is None:
                    continue
                results[snapshot.exchange][snapshot.symbol] = snapshot

        return results

    def _fetch_one(
        self,
        exchange_name: str,
        client: ccxt.Exchange,
        symbol: str,
    ) -> TickerSnapshot | None:
        try:
            ticker = client.fetch_ticker(symbol)
            bid = float(ticker.get("bid") or 0.0)
            ask = float(ticker.get("ask") or 0.0)
            if bid <= 0 or ask <= 0:
                return None

            bid_volume = float(ticker.get("bidVolume") or 0.0)
            ask_volume = float(ticker.get("askVolume") or 0.0)
            timestamp_ms = int(ticker.get("timestamp") or int(time.time() * 1000))

            bid_depth_price = 0.0
            ask_depth_price = 0.0
            bid_depth_base = 0.0
            ask_depth_base = 0.0

            if self.config.enable_orderbook_depth:
                try:
                    orderbook = client.fetch_order_book(
                        symbol,
                        limit=self.config.orderbook_depth_levels,
                    )
                    ask_depth_price, ask_depth_base = _impact_price_for_quote(
                        orderbook.get("asks", []),
                        self.config.orderbook_impact_notional_usdt,
                    )
                    bid_depth_price, bid_depth_base = _impact_price_for_quote(
                        orderbook.get("bids", []),
                        self.config.orderbook_impact_notional_usdt,
                    )
                except Exception as exc:
                    logger.debug(
                        "fetch_order_book failed | %s %s | %s",
                        exchange_name,
                        symbol,
                        exc,
                    )

            return TickerSnapshot(
                exchange=exchange_name,
                symbol=symbol,
                bid=bid,
                ask=ask,
                bid_volume=bid_volume,
                ask_volume=ask_volume,
                timestamp_ms=timestamp_ms,
                bid_depth_price=bid_depth_price,
                ask_depth_price=ask_depth_price,
                bid_depth_base=bid_depth_base,
                ask_depth_base=ask_depth_base,
            )
        except Exception as exc:
            logger.debug("fetch_ticker failed | %s %s | %s", exchange_name, symbol, exc)
            return None

    def close(self) -> None:
        for client in self.clients.values():
            try:
                client.close()
            except Exception:
                continue


def _env_or_empty(name: str) -> str:
    import os

    return os.getenv(name, "").strip()


def _impact_price_for_quote(
    levels: List[list],
    target_quote: float,
) -> tuple[float, float]:
    if target_quote <= 0:
        return 0.0, 0.0

    total_quote = 0.0
    total_base = 0.0
    for level in levels:
        if len(level) < 2:
            continue
        price = float(level[0] or 0.0)
        qty = float(level[1] or 0.0)
        if price <= 0 or qty <= 0:
            continue

        level_quote = price * qty
        remain_quote = target_quote - total_quote
        if remain_quote <= 0:
            break

        take_quote = min(level_quote, remain_quote)
        take_base = take_quote / price

        total_quote += take_quote
        total_base += take_base

        if total_quote >= target_quote:
            break

    if total_base <= 0:
        return 0.0, 0.0

    effective_price = total_quote / total_base
    return effective_price, total_base
