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
        self.exchange_slippage_ewma_pct: Dict[str, float] = {
            ex: max(0.0, config.slippage_pct) for ex in config.exchanges
        }
        self.execution_diagnostics_last_cycle: Dict[str, float] = {}

    def find_opportunities(
        self,
        market: Dict[str, Dict[str, TickerSnapshot]],
    ) -> List[Opportunity]:
        opportunities: List[Opportunity] = []
        now_ms = int(time.time() * 1000)
        cycle_rejections: Dict[str, int] = defaultdict(int)
        net_spread_samples: List[float] = []
        threshold_samples: List[float] = []
        fill_prob_samples: List[float] = []
        queue_risk_samples: List[float] = []

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
                        threshold_samples.append(opp.dynamic_threshold_pct)
                        fill_prob_samples.append(opp.fill_probability)
                        queue_risk_samples.append(opp.queue_risk_score)
                    elif reject_reason is not None:
                        cycle_rejections[reject_reason] += 1

        opportunities.sort(key=lambda x: x.expected_profit_usdt, reverse=True)
        self.rejection_counts_last_cycle = dict(cycle_rejections)
        for reason, count in cycle_rejections.items():
            self.rejection_counts_total[reason] = self.rejection_counts_total.get(reason, 0) + count
        self.net_spread_distribution_last_cycle = _distribution(net_spread_samples)
        self.execution_diagnostics_last_cycle = {
            "avg_dynamic_threshold_pct": _average(threshold_samples),
            "avg_fill_probability": _average(fill_prob_samples),
            "avg_queue_risk": _average(queue_risk_samples),
        }
        return opportunities

    def get_rejection_counts(self) -> Dict[str, Dict[str, int]]:
        return {
            "last_cycle": dict(self.rejection_counts_last_cycle),
            "total": dict(self.rejection_counts_total),
        }

    def get_net_spread_distribution(self) -> Dict[str, float]:
        return dict(self.net_spread_distribution_last_cycle)

    def get_execution_diagnostics(self) -> Dict[str, float]:
        return dict(self.execution_diagnostics_last_cycle)

    def _build_opportunity(
        self,
        buy_row: TickerSnapshot,
        sell_row: TickerSnapshot,
    ) -> tuple[Opportunity | None, str | None, float | None]:
        taker_buy_price = buy_row.ask
        taker_sell_price = sell_row.bid
        taker_buy_source = "ticker"
        taker_sell_source = "ticker"

        if buy_row.ask_depth_price > 0:
            taker_buy_price = buy_row.ask_depth_price
            taker_buy_source = "orderbook"
        if sell_row.bid_depth_price > 0:
            taker_sell_price = sell_row.bid_depth_price
            taker_sell_source = "orderbook"

        dynamic_buy_slippage_pct = 0.0
        dynamic_sell_slippage_pct = 0.0
        if buy_row.ask > 0:
            dynamic_buy_slippage_pct = max(0.0, ((taker_buy_price - buy_row.ask) / buy_row.ask) * 100.0)
        if sell_row.bid > 0:
            dynamic_sell_slippage_pct = max(0.0, ((sell_row.bid - taker_sell_price) / sell_row.bid) * 100.0)

        self._update_exchange_slippage(buy_row.exchange, dynamic_buy_slippage_pct)
        self._update_exchange_slippage(sell_row.exchange, dynamic_sell_slippage_pct)

        maker_side = "none"
        taker_side = "both"
        execution_style = self.config.execution_style
        if execution_style not in {"taker-taker", "maker-taker"}:
            execution_style = "taker-taker"

        buy_price = taker_buy_price
        sell_price = taker_sell_price
        buy_source = taker_buy_source
        sell_source = taker_sell_source
        buy_fee = self.config.fees_taker.get(buy_row.exchange, 0.001)
        sell_fee = self.config.fees_taker.get(sell_row.exchange, 0.001)
        buy_slippage_pct = self._select_slippage_pct(buy_row.exchange, dynamic_buy_slippage_pct)
        sell_slippage_pct = self._select_slippage_pct(sell_row.exchange, dynamic_sell_slippage_pct)
        maker_exchange = ""
        taker_exchange = ""
        maker_queue_base = 0.0
        taker_depth_base = min_nonzero(buy_row.ask_depth_base, sell_row.bid_depth_base)

        if execution_style == "maker-taker":
            maker_side = self._maker_side()
            if maker_side == "sell":
                maker_side = "sell"
                taker_side = "buy"
                maker_exchange = sell_row.exchange
                taker_exchange = buy_row.exchange
                buy_price = taker_buy_price
                sell_price = sell_row.ask if sell_row.ask > 0 else sell_row.bid
                buy_source = taker_buy_source
                sell_source = "ticker"
                buy_fee = self.config.fees_taker.get(buy_row.exchange, 0.001)
                sell_fee = self.config.fees_maker.get(sell_row.exchange, 0.0006)
                buy_slippage_pct = self._select_slippage_pct(buy_row.exchange, dynamic_buy_slippage_pct)
                sell_slippage_pct = 0.0
                maker_queue_base = max(sell_row.ask_volume, 0.0)
                taker_depth_base = buy_row.ask_depth_base
            else:
                maker_side = "buy"
                taker_side = "sell"
                maker_exchange = buy_row.exchange
                taker_exchange = sell_row.exchange
                buy_price = buy_row.bid if buy_row.bid > 0 else buy_row.ask
                sell_price = taker_sell_price
                buy_source = "ticker"
                sell_source = taker_sell_source
                buy_fee = self.config.fees_maker.get(buy_row.exchange, 0.0006)
                sell_fee = self.config.fees_taker.get(sell_row.exchange, 0.001)
                buy_slippage_pct = 0.0
                sell_slippage_pct = self._select_slippage_pct(sell_row.exchange, dynamic_sell_slippage_pct)
                maker_queue_base = max(buy_row.bid_volume, 0.0)
                taker_depth_base = sell_row.bid_depth_base
        else:
            maker_exchange = ""
            taker_exchange = ""

        if self.config.require_depth_liquidity:
            if execution_style == "taker-taker":
                if buy_row.ask_depth_price <= 0 or sell_row.bid_depth_price <= 0:
                    return None, "depth_liquidity_missing", None
            elif taker_side == "buy" and buy_row.ask_depth_price <= 0:
                return None, "depth_liquidity_missing", None
            elif taker_side == "sell" and sell_row.bid_depth_price <= 0:
                return None, "depth_liquidity_missing", None

        if buy_price <= 0 or sell_price <= 0:
            return None, "invalid_price", None

        fee_cost_pct = (buy_fee + sell_fee) * 100.0
        slippage_cost_pct = buy_slippage_pct + sell_slippage_pct
        dynamic_threshold_pct = self._effective_dynamic_threshold(
            buy_exchange=buy_row.exchange,
            sell_exchange=sell_row.exchange,
            buy_fee=buy_fee,
            sell_fee=sell_fee,
            buy_slippage_pct=buy_slippage_pct,
            sell_slippage_pct=sell_slippage_pct,
        )

        buy_slippage = buy_slippage_pct / 100.0
        sell_slippage = sell_slippage_pct / 100.0

        gross_spread_pct = ((sell_price - buy_price) / buy_price) * 100.0
        net_buy = buy_price * (1.0 + buy_fee + buy_slippage)
        net_sell = sell_price * (1.0 - sell_fee - sell_slippage)
        net_spread_pct = ((net_sell - net_buy) / net_buy) * 100.0

        if net_spread_pct < dynamic_threshold_pct:
            return None, "net_spread_below_auto_threshold", net_spread_pct

        qty_from_cap = self.config.capital_per_trade_usdt / buy_price
        qty_constraints = [qty_from_cap, self.config.max_position_per_symbol]
        if execution_style == "maker-taker":
            qty_constraints.extend([maker_queue_base, taker_depth_base])
            if taker_side == "buy":
                qty_constraints.append(buy_row.ask_volume)
            else:
                qty_constraints.append(sell_row.bid_volume)
        else:
            qty_constraints.extend(
                [
                    buy_row.ask_volume,
                    sell_row.bid_volume,
                    buy_row.ask_depth_base,
                    sell_row.bid_depth_base,
                ]
            )

        quantity = min_nonzero(*qty_constraints)
        notional = quantity * buy_price
        if quantity <= 0 or notional < self.config.min_notional_usdt:
            return None, "insufficient_trade_size", net_spread_pct

        queue_risk_score = 0.0
        fill_probability = 1.0
        expected_fill_time_ms = 0
        if execution_style == "maker-taker":
            queue_risk_score = self._estimate_queue_risk(quantity, maker_queue_base)
            fill_probability = self._estimate_fill_probability(
                net_spread_pct=net_spread_pct,
                dynamic_threshold_pct=dynamic_threshold_pct,
                queue_risk_score=queue_risk_score,
                quantity=quantity,
                taker_depth_base=taker_depth_base,
                buy_row=buy_row,
                sell_row=sell_row,
            )
            expected_fill_time_ms = int(
                self.config.maker_order_timeout_ms
                * _clamp(1.2 - fill_probability + (queue_risk_score * 0.4), 0.25, 2.5)
            )

        expected_profit_usdt = quantity * (net_sell - net_buy)
        if expected_profit_usdt <= 0:
            return None, "non_positive_expected_profit", net_spread_pct

        return Opportunity(
            symbol=buy_row.symbol,
            execution_style=execution_style,
            buy_exchange=buy_row.exchange,
            sell_exchange=sell_row.exchange,
            maker_exchange=maker_exchange,
            taker_exchange=taker_exchange,
            maker_side=maker_side,
            taker_side=taker_side,
            buy_price=buy_price,
            sell_price=sell_price,
            buy_price_source=buy_source,
            sell_price_source=sell_source,
            buy_fee_pct=buy_fee * 100.0,
            sell_fee_pct=sell_fee * 100.0,
            buy_slippage_pct=buy_slippage_pct,
            sell_slippage_pct=sell_slippage_pct,
            fee_cost_pct=fee_cost_pct,
            slippage_cost_pct=slippage_cost_pct,
            dynamic_threshold_pct=dynamic_threshold_pct,
            queue_risk_score=queue_risk_score,
            fill_probability=fill_probability,
            expected_fill_time_ms=expected_fill_time_ms,
            gross_spread_pct=gross_spread_pct,
            net_spread_pct=net_spread_pct,
            quantity=quantity,
            expected_profit_usdt=expected_profit_usdt,
            timestamp_ms=int(time.time() * 1000),
        ), None, net_spread_pct

    def _maker_side(self) -> str:
        side = self.config.maker_side_preference
        if side in {"buy", "sell"}:
            return side
        return "buy"

    def _select_slippage_pct(self, exchange: str, dynamic_slippage_pct: float) -> float:
        base_slippage = max(0.0, self.config.slippage_pct)
        if self.config.use_dynamic_slippage:
            return max(base_slippage, dynamic_slippage_pct, self.exchange_slippage_ewma_pct.get(exchange, 0.0))
        return base_slippage

    def _update_exchange_slippage(self, exchange: str, observed_slippage_pct: float) -> None:
        prev = self.exchange_slippage_ewma_pct.get(exchange, self.config.slippage_pct)
        alpha = 0.25
        self.exchange_slippage_ewma_pct[exchange] = max(0.0, (alpha * observed_slippage_pct) + ((1.0 - alpha) * prev))

    def _effective_dynamic_threshold(
        self,
        buy_exchange: str,
        sell_exchange: str,
        buy_fee: float,
        sell_fee: float,
        buy_slippage_pct: float,
        sell_slippage_pct: float,
    ) -> float:
        base_threshold = self.config.min_net_spread_pct
        if not self.config.auto_threshold_enabled:
            return base_threshold

        buy_rt_slippage = max(
            buy_slippage_pct,
            self.exchange_slippage_ewma_pct.get(buy_exchange, self.config.slippage_pct),
        )
        sell_rt_slippage = max(
            sell_slippage_pct,
            self.exchange_slippage_ewma_pct.get(sell_exchange, self.config.slippage_pct),
        )
        total_cost_pct = ((buy_fee + sell_fee) * 100.0) + buy_rt_slippage + sell_rt_slippage
        dynamic_floor = max(
            self.config.auto_threshold_min_floor_pct,
            total_cost_pct * self.config.auto_threshold_cost_buffer_ratio,
        )
        return max(base_threshold, dynamic_floor)

    def _estimate_queue_risk(self, quantity: float, maker_queue_base: float) -> float:
        if maker_queue_base <= 0:
            return 1.0
        pressure = quantity / maker_queue_base
        return _clamp(pressure * self.config.queue_risk_sensitivity, 0.0, 1.5)

    def _estimate_fill_probability(
        self,
        net_spread_pct: float,
        dynamic_threshold_pct: float,
        queue_risk_score: float,
        quantity: float,
        taker_depth_base: float,
        buy_row: TickerSnapshot,
        sell_row: TickerSnapshot,
    ) -> float:
        edge_buffer = net_spread_pct - dynamic_threshold_pct
        edge_score = _clamp(edge_buffer / max(self.config.fill_probability_edge_ref_pct, 0.01), -1.0, 1.0)
        depth_score = _clamp((taker_depth_base / max(quantity, 1e-9)) / 1.5, 0.0, 1.0)
        source_score = 0.0
        if buy_row.market_data_source == "ws":
            source_score += 0.05
        if sell_row.market_data_source == "ws":
            source_score += 0.05

        score = 0.45 + (0.25 * depth_score) + (0.25 * max(edge_score, 0.0)) - (0.35 * queue_risk_score) + source_score
        return _clamp(score, 0.01, 0.99)


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


def _average(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
