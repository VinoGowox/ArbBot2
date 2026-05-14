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
    market_data_source: str = "rest"


@dataclass
class Opportunity:
    symbol: str
    execution_style: str
    buy_exchange: str
    sell_exchange: str
    maker_exchange: str
    taker_exchange: str
    maker_side: str
    taker_side: str
    buy_price: float
    sell_price: float
    buy_price_source: str
    sell_price_source: str
    buy_fee_pct: float
    sell_fee_pct: float
    buy_slippage_pct: float
    sell_slippage_pct: float
    fee_cost_pct: float
    slippage_cost_pct: float
    dynamic_threshold_pct: float
    queue_risk_score: float
    fill_probability: float
    expected_fill_time_ms: int
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
