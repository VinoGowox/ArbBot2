from __future__ import annotations

import time
from typing import Dict, List

from .config import BotConfig
from .models import Opportunity, TickerSnapshot


class OpportunityEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def find_opportunities(
        self,
        market: Dict[str, Dict[str, TickerSnapshot]],
    ) -> List[Opportunity]:
        opportunities: List[Opportunity] = []
        now_ms = int(time.time() * 1000)

        for symbol in self.config.symbols:
            rows = []
            for exchange_name, by_symbol in market.items():
                snap = by_symbol.get(symbol)
                if snap is None:
                    continue
                if now_ms - snap.timestamp_ms > self.config.max_data_age_ms:
                    continue
                rows.append(snap)

            if len(rows) < 2:
                continue

            for buy_row in rows:
                for sell_row in rows:
                    if buy_row.exchange == sell_row.exchange:
                        continue
                    opp = self._build_opportunity(buy_row, sell_row)
                    if opp is not None:
                        opportunities.append(opp)

        opportunities.sort(key=lambda x: x.expected_profit_usdt, reverse=True)
        return opportunities

    def _build_opportunity(
        self,
        buy_row: TickerSnapshot,
        sell_row: TickerSnapshot,
    ) -> Opportunity | None:
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
                return None

        buy_fee = self.config.fees_taker.get(buy_row.exchange, 0.001)
        sell_fee = self.config.fees_taker.get(sell_row.exchange, 0.001)
        slippage = self.config.slippage_pct / 100.0

        gross_spread_pct = ((sell_price - buy_price) / buy_price) * 100.0
        net_buy = buy_price * (1.0 + buy_fee + slippage)
        net_sell = sell_price * (1.0 - sell_fee - slippage)
        net_spread_pct = ((net_sell - net_buy) / net_buy) * 100.0

        if net_spread_pct < self.config.min_net_spread_pct:
            return None

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
            return None

        expected_profit_usdt = quantity * (net_sell - net_buy)
        if expected_profit_usdt <= 0:
            return None

        return Opportunity(
            symbol=buy_row.symbol,
            buy_exchange=buy_row.exchange,
            sell_exchange=sell_row.exchange,
            buy_price=buy_price,
            sell_price=sell_price,
            buy_price_source=buy_source,
            sell_price_source=sell_source,
            gross_spread_pct=gross_spread_pct,
            net_spread_pct=net_spread_pct,
            quantity=quantity,
            expected_profit_usdt=expected_profit_usdt,
            timestamp_ms=int(time.time() * 1000),
        )


def min_nonzero(*values: float) -> float:
    candidates = [v for v in values if v > 0]
    if not candidates:
        return 0.0
    return min(candidates)
