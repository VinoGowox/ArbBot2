from src.config import load_config
from src.models import TickerSnapshot
from src.opportunity import OpportunityEngine


def test_find_opportunity_positive_spread() -> None:
    cfg = load_config()
    cfg.execution_style = "taker-taker"
    cfg.min_net_spread_pct = -1.0
    cfg.require_depth_liquidity = False
    cfg.auto_threshold_enabled = False
    engine = OpportunityEngine(cfg)

    market = {
        "binance": {
            "BTC/USDT": TickerSnapshot(
                exchange="binance",
                symbol="BTC/USDT",
                bid=69000,
                ask=69010,
                bid_volume=1,
                ask_volume=1,
                timestamp_ms=9999999999999,
            )
        },
        "bybit": {
            "BTC/USDT": TickerSnapshot(
                exchange="bybit",
                symbol="BTC/USDT",
                bid=69380,
                ask=69390,
                bid_volume=1,
                ask_volume=1,
                timestamp_ms=9999999999999,
            )
        },
    }

    opportunities = engine.find_opportunities(market)
    assert len(opportunities) >= 1


def test_maker_taker_fields_present() -> None:
    cfg = load_config()
    cfg.execution_style = "maker-taker"
    cfg.maker_side_preference = "buy"
    cfg.min_net_spread_pct = -1.0
    cfg.require_depth_liquidity = False
    cfg.auto_threshold_enabled = True
    engine = OpportunityEngine(cfg)

    market = {
        "binance": {
            "BTC/USDT": TickerSnapshot(
                exchange="binance",
                symbol="BTC/USDT",
                bid=69000,
                ask=69002,
                bid_volume=3,
                ask_volume=3,
                timestamp_ms=9999999999999,
                ask_depth_price=69003,
                bid_depth_price=68999,
                ask_depth_base=3,
                bid_depth_base=3,
                market_data_source="ws",
            )
        },
        "bybit": {
            "BTC/USDT": TickerSnapshot(
                exchange="bybit",
                symbol="BTC/USDT",
                bid=69410,
                ask=69415,
                bid_volume=3,
                ask_volume=3,
                timestamp_ms=9999999999999,
                ask_depth_price=69416,
                bid_depth_price=69408,
                ask_depth_base=3,
                bid_depth_base=3,
                market_data_source="ws",
            )
        },
    }

    opportunities = engine.find_opportunities(market)
    assert len(opportunities) >= 1
    best = opportunities[0]
    assert best.execution_style == "maker-taker"
    assert best.maker_side in {"buy", "sell"}
    assert 0.0 <= best.fill_probability <= 1.0
    assert best.dynamic_threshold_pct >= cfg.min_net_spread_pct
