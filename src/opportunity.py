from __future__ import annotations

from collections import defaultdict
import time
from typing import Dict, List

from .config import BotConfig
from .models import Opportunity, TickerSnapshot


class OpportunityEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.rejection_counts_last_cycle: Dict[str, int] = {}
        self.rejection_counts_total: Dict[str, int] = {}
        self.net_spread_distribution_last_cycle: Dict[str, float] = {}

    def find_opportunities(
        self,
        market: Dict[str, Dict[str, TickerSnapshot]],
    ) -> List[Opportunity]:
        opportunities: List[Opportunity] = []
        now_ms = int(time.time() * 1000)
        cycle_rejections: Dict[str, int] = defaultdict(int)
        net_spread_samples: List[float] = []

        for symbol in self.config.symbols:
            rows = []
            for exchange_name, by_symbol in market.items():
                snap = by_symbol.get(symbol)
                if snap is None:
                    cycle_rejections["missing_snapshot"] += 1
                    continue
                if now_ms - snap.timestamp_ms > self.config.max_data_age_ms:
                    cycle_rejections["stale_snapshot"] += 1
                    continue
                rows.append(snap)

            if len(rows) < 2:
                cycle_rejections["insufficient_fresh_markets"] += 1
                continue

            for buy_row in rows:
                for sell_row in rows:
                    if buy_row.exchange == sell_row.exchange:
                        continue
                    opp, reject_reason, net_spread_pct = self._build_opportunity(buy_row, sell_row)
                    if net_spread_pct is not None:
                        net_spread_samples.append(net_spread_pct)
                    if opp is not None:
                        opportunities.append(opp)
                    elif reject_reason is not None:
                        cycle_rejections[reject_reason] += 1

        opportunities.sort(key=lambda x: x.expected_profit_usdt, reverse=True)
        self.rejection_counts_last_cycle = dict(cycle_rejections)
        for reason, count in cycle_rejections.items():
            self.rejection_counts_total[reason] = self.rejection_counts_total.get(reason, 0) + count
        self.net_spread_distribution_last_cycle = _distribution(net_spread_samples)
        return opportunities

    def get_rejection_counts(self) -> Dict[str, Dict[str, int]]:
        return {
            "last_cycle": dict(self.rejection_counts_last_cycle),
            "total": dict(self.rejection_counts_total),
        }

    def get_net_spread_distribution(self) -> Dict[str, float]:
        return dict(self.net_spread_distribution_last_cycle)

    def _build_opportunity(
        self,
        buy_row: TickerSnapshot,
        sell_row: TickerSnapshot,
    ) -> tuple[Opportunity | None, str | None, float | None]:
        buy_price = buy_row.ask
        sell_price = sell_row.bid
        buy_source = "ticker"
        sell_source = "ticker"

        if buy_row.ask_depth_price > 0:
            buy_price = buy_row.ask_depth_price
            buy_source = "orderbook"
        if sell_row.bid_depth_price > 0:
            sell_price = sell_row.bid_depth_price
            sell_source = "orderbook"

        if self.config.require_depth_liquidity:
            if buy_row.ask_depth_price <= 0 or sell_row.bid_depth_price <= 0:
                return None, "depth_liquidity_missing", None

        buy_fee = self.config.fees_taker.get(buy_row.exchange, 0.001)
        sell_fee = self.config.fees_taker.get(sell_row.exchange, 0.001)

        dynamic_buy_slippage_pct = 0.0
        dynamic_sell_slippage_pct = 0.0
        if buy_row.ask > 0:
            dynamic_buy_slippage_pct = max(0.0, ((buy_price - buy_row.ask) / buy_row.ask) * 100.0)
        if sell_row.bid > 0:
            dynamic_sell_slippage_pct = max(0.0, ((sell_row.bid - sell_price) / sell_row.bid) * 100.0)

        if self.config.use_dynamic_slippage:
            buy_slippage_pct = max(self.config.slippage_pct, dynamic_buy_slippage_pct)
            sell_slippage_pct = max(self.config.slippage_pct, dynamic_sell_slippage_pct)
        else:
            buy_slippage_pct = self.config.slippage_pct
            sell_slippage_pct = self.config.slippage_pct

        buy_slippage = buy_slippage_pct / 100.0
        sell_slippage = sell_slippage_pct / 100.0

        gross_spread_pct = ((sell_price - buy_price) / buy_price) * 100.0
        net_buy = buy_price * (1.0 + buy_fee + buy_slippage)
        net_sell = sell_price * (1.0 - sell_fee - sell_slippage)
        net_spread_pct = ((net_sell - net_buy) / net_buy) * 100.0

        if net_spread_pct < self.config.min_net_spread_pct:
            return None, "net_spread_below_threshold", net_spread_pct

        qty_from_cap = self.config.capital_per_trade_usdt / buy_price
        quantity = min_nonzero(
            qty_from_cap,
            buy_row.ask_volume,
            sell_row.bid_volume,
            buy_row.ask_depth_base,
            sell_row.bid_depth_base,
            self.config.max_position_per_symbol,
        )

        notional = quantity * buy_price
        if quantity <= 0 or notional < self.config.min_notional_usdt:
            return None, "insufficient_trade_size", net_spread_pct

        expected_profit_usdt = quantity * (net_sell - net_buy)
        if expected_profit_usdt <= 0:
            return None, "non_positive_expected_profit", net_spread_pct

        return Opportunity(
            symbol=buy_row.symbol,
            buy_exchange=buy_row.exchange,
            sell_exchange=sell_row.exchange,
            buy_price=buy_price,
            sell_price=sell_price,
            buy_price_source=buy_source,
            sell_price_source=sell_source,
            buy_fee_pct=buy_fee * 100.0,
            sell_fee_pct=sell_fee * 100.0,
            buy_slippage_pct=buy_slippage_pct,
            sell_slippage_pct=sell_slippage_pct,
            gross_spread_pct=gross_spread_pct,
            net_spread_pct=net_spread_pct,
            quantity=quantity,
            expected_profit_usdt=expected_profit_usdt,
            timestamp_ms=int(time.time() * 1000),
        ), None, net_spread_pct


def min_nonzero(*values: float) -> float:
    candidates = [v for v in values if v > 0]
    if not candidates:
        return 0.0
    return min(candidates)


def _distribution(samples: List[float]) -> Dict[str, float]:
    if not samples:
        return {"count": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0, "min": 0.0}

    sorted_samples = sorted(samples)
    return {
        "count": float(len(sorted_samples)),
        "p50": _percentile(sorted_samples, 50.0),
        "p90": _percentile(sorted_samples, 90.0),
        "max": sorted_samples[-1],
        "min": sorted_samples[0],
    }


def _percentile(sorted_samples: List[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0

    if pct <= 0:
        return sorted_samples[0]
    if pct >= 100:
        return sorted_samples[-1]

    position = (len(sorted_samples) - 1) * (pct / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(sorted_samples) - 1)
    weight = position - lower
    return sorted_samples[lower] * (1.0 - weight) + sorted_samples[upper] * weight
