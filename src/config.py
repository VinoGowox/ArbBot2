from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List

from dotenv import load_dotenv


@dataclass
class BotConfig:
    mode: str
    execution_style: str
    maker_side_preference: str
    exchanges: List[str]
    symbols: List[str]
    poll_interval_sec: float
    min_net_spread_pct: float
    slippage_pct: float
    use_dynamic_slippage: bool
    auto_threshold_enabled: bool
    auto_threshold_cost_buffer_ratio: float
    auto_threshold_min_floor_pct: float
    fill_probability_edge_ref_pct: float
    queue_risk_sensitivity: float
    maker_order_timeout_ms: int
    maker_max_requotes: int
    maker_requote_step_bps: float
    maker_min_fill_probability: float
    maker_requote_fill_boost: float
    allow_negative_expected_profit_dryrun: bool
    max_data_age_ms: int
    max_daily_drawdown_pct: float
    capital_per_exchange_usdt: float
    capital_per_trade_usdt: float
    max_position_per_symbol: float
    min_notional_usdt: float
    trade_cooldown_sec: float
    max_consecutive_failures: int
    rebalance_threshold_pct: float
    rebalance_interval_sec: int
    rebalance_fee_pct: float
    status_log_interval_sec: int
    max_opportunities_per_cycle: int
    max_opportunity_age_ms: int
    enable_orderbook_depth: bool
    enable_websocket_market_data: bool
    websocket_stale_ms: int
    require_depth_liquidity: bool
    orderbook_depth_levels: int
    orderbook_impact_notional_usdt: float
    dashboard_enabled: bool
    dashboard_host: str
    dashboard_port: int
    telegram_bot_token: str
    telegram_chat_id: str
    fees_taker: Dict[str, float]
    fees_maker: Dict[str, float]


def _csv_env(name: str, default: str) -> List[str]:
    value = os.getenv(name, default)
    return [part.strip() for part in value.split(",") if part.strip()]


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> BotConfig:
    load_dotenv()

    exchanges = [x.lower() for x in _csv_env("EXCHANGES", "binance,bybit,okx,kucoin")]
    default_fees_taker = {
        "binance": 0.001,
        "bybit": 0.001,
        "okx": 0.001,
        "kucoin": 0.001,
    }
    fees_taker = {
        ex: _float_env(
            f"FEE_TAKER_{ex.upper()}",
            default_fees_taker.get(ex, 0.001),
        )
        for ex in exchanges
    }
    fees_maker = {
        ex: _float_env(
            f"FEE_MAKER_{ex.upper()}",
            max(0.0, default_fees_taker.get(ex, 0.001) * 0.6),
        )
        for ex in exchanges
    }

    return BotConfig(
        mode=os.getenv("MODE", "paper").lower(),
        execution_style=os.getenv("EXECUTION_STYLE", "taker-taker").strip().lower(),
        maker_side_preference=os.getenv("MAKER_SIDE_PREFERENCE", "buy").strip().lower(),
        exchanges=exchanges,
        symbols=_csv_env("SYMBOLS", "BTC/USDT,ETH/USDT"),
        poll_interval_sec=_float_env("POLL_INTERVAL_SEC", 2.0),
        min_net_spread_pct=_float_env("MIN_NET_SPREAD_PCT", 0.15),
        slippage_pct=_float_env("SLIPPAGE_PCT", 0.05),
        use_dynamic_slippage=_bool_env("USE_DYNAMIC_SLIPPAGE", True),
        auto_threshold_enabled=_bool_env("AUTO_THRESHOLD_ENABLED", True),
        auto_threshold_cost_buffer_ratio=_float_env("AUTO_THRESHOLD_COST_BUFFER_RATIO", 0.25),
        auto_threshold_min_floor_pct=_float_env("AUTO_THRESHOLD_MIN_FLOOR_PCT", 0.03),
        fill_probability_edge_ref_pct=_float_env("FILL_PROBABILITY_EDGE_REF_PCT", 0.12),
        queue_risk_sensitivity=_float_env("QUEUE_RISK_SENSITIVITY", 1.0),
        maker_order_timeout_ms=_int_env("MAKER_ORDER_TIMEOUT_MS", 1200),
        maker_max_requotes=_int_env("MAKER_MAX_REQUOTES", 2),
        maker_requote_step_bps=_float_env("MAKER_REQUOTE_STEP_BPS", 0.8),
        maker_min_fill_probability=_float_env("MAKER_MIN_FILL_PROBABILITY", 0.45),
        maker_requote_fill_boost=_float_env("MAKER_REQUOTE_FILL_BOOST", 0.12),
        allow_negative_expected_profit_dryrun=_bool_env(
            "ALLOW_NEGATIVE_EXPECTED_PROFIT_DRYRUN",
            False,
        ),
        max_data_age_ms=_int_env("MAX_DATA_AGE_MS", 3500),
        max_daily_drawdown_pct=_float_env("MAX_DAILY_DRAWDOWN_PCT", 1.0),
        capital_per_exchange_usdt=_float_env("CAPITAL_PER_EXCHANGE_USDT", 1000.0),
        capital_per_trade_usdt=_float_env("CAPITAL_PER_TRADE_USDT", 150.0),
        max_position_per_symbol=_float_env("MAX_POSITION_PER_SYMBOL", 0.02),
        min_notional_usdt=_float_env("MIN_NOTIONAL_USDT", 20.0),
        trade_cooldown_sec=_float_env("TRADE_COOLDOWN_SEC", 8.0),
        max_consecutive_failures=_int_env("MAX_CONSECUTIVE_FAILURES", 8),
        rebalance_threshold_pct=_float_env("REBALANCE_THRESHOLD_PCT", 35.0),
        rebalance_interval_sec=_int_env("REBALANCE_INTERVAL_SEC", 120),
        rebalance_fee_pct=_float_env("REBALANCE_FEE_PCT", 0.02),
        status_log_interval_sec=_int_env("STATUS_LOG_INTERVAL_SEC", 30),
        max_opportunities_per_cycle=_int_env("MAX_OPPORTUNITIES_PER_CYCLE", 3),
        max_opportunity_age_ms=_int_env("MAX_OPPORTUNITY_AGE_MS", 1200),
        enable_orderbook_depth=_bool_env("ENABLE_ORDERBOOK_DEPTH", True),
        enable_websocket_market_data=_bool_env("ENABLE_WEBSOCKET_MARKET_DATA", True),
        websocket_stale_ms=_int_env("WEBSOCKET_STALE_MS", 6000),
        require_depth_liquidity=_bool_env("REQUIRE_DEPTH_LIQUIDITY", True),
        orderbook_depth_levels=_int_env("ORDERBOOK_DEPTH_LEVELS", 5),
        orderbook_impact_notional_usdt=_float_env("ORDERBOOK_IMPACT_NOTIONAL_USDT", 150.0),
        dashboard_enabled=_bool_env("DASHBOARD_ENABLED", True),
        dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1").strip(),
        dashboard_port=_int_env("DASHBOARD_PORT", 8080),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        fees_taker=fees_taker,
        fees_maker=fees_maker,
    )
