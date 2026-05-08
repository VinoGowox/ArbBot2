from src.config import load_config
from src.models import TickerSnapshot
from src.opportunity import OpportunityEngine


def test_find_opportunity_positive_spread() -> None:
    cfg = load_config()
    cfg.min_net_spread_pct = -1.0
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
                bid=69120,
                ask=69125,
                bid_volume=1,
                ask_volume=1,
                timestamp_ms=9999999999999,
            )
        },
    }

    opportunities = engine.find_opportunities(market)
    assert len(opportunities) >= 1
