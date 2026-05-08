from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class TickerSnapshot:
    exchange: str
    symbol: str
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float
    timestamp_ms: int
    bid_depth_price: float = 0.0
    ask_depth_price: float = 0.0
    bid_depth_base: float = 0.0
    ask_depth_base: float = 0.0


@dataclass
class Opportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    buy_price_source: str
    sell_price_source: str
    gross_spread_pct: float
    net_spread_pct: float
    quantity: float
    expected_profit_usdt: float
    timestamp_ms: int


@dataclass
class TradeResult:
    success: bool
    reason: str
    symbol: str
    buy_exchange: str
    sell_exchange: str
    quantity: float
    realized_pnl_usdt: float


@dataclass
class ExchangeBalance:
    quote_free: float
    base_free: Dict[str, float]
