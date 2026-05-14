from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict

from .config import BotConfig
from .models import ExchangeBalance, Opportunity, TradeResult

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    realized_pnl_usdt: float = 0.0
    blocked: bool = False
    blocked_reason: str = ""
    trades_executed: int = 0
    trades_failed: int = 0
    consecutive_failures: int = 0
    maker_timeouts: int = 0
    maker_requotes: int = 0


class PaperExecutor:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.mode = config.mode
        self.risk = RiskState()
        self.balances = self._init_balances()
        self.last_trade_at: Dict[str, float] = {}
        self.last_rebalance_at: Dict[str, float] = {}
        self.last_order_payload: Dict[str, object] = {}

    def _init_balances(self) -> Dict[str, ExchangeBalance]:
        balances: Dict[str, ExchangeBalance] = {}
        for ex in self.config.exchanges:
            base_inventory = defaultdict(float)
            for symbol in self.config.symbols:
                base, _ = symbol.split("/")
                base_inventory[base] = self.config.max_position_per_symbol * 3

            balances[ex] = ExchangeBalance(
                quote_free=self.config.capital_per_exchange_usdt,
                base_free=dict(base_inventory),
            )
        return balances

    def execute(self, opp: Opportunity) -> TradeResult:
        if self.risk.blocked:
            return self._register_failure(
                success=False,
                reason=self.risk.blocked_reason or "risk_blocked",
                symbol=opp.symbol,
                buy_exchange=opp.buy_exchange,
                sell_exchange=opp.sell_exchange,
                quantity=opp.quantity,
                realized_pnl_usdt=0.0,
            )

        route_key = self._route_key(opp)
        now_ts = time.time()
        last_ts = self.last_trade_at.get(route_key)
        if last_ts is not None and (now_ts - last_ts) < self.config.trade_cooldown_sec:
            return self._register_failure(
                success=False,
                reason="cooldown_active",
                symbol=opp.symbol,
                buy_exchange=opp.buy_exchange,
                sell_exchange=opp.sell_exchange,
                quantity=opp.quantity,
                realized_pnl_usdt=0.0,
            )

        base, _ = opp.symbol.split("/")
        buy_bal = self.balances.get(opp.buy_exchange)
        sell_bal = self.balances.get(opp.sell_exchange)
        if buy_bal is None or sell_bal is None:
            return self._failed("unknown_exchange", opp)

        buy_cost = opp.quantity * opp.buy_price
        if buy_bal.quote_free < buy_cost:
            return self._failed("insufficient_quote_on_buy_exchange", opp)

        if sell_bal.base_free.get(base, 0.0) < opp.quantity:
            return self._failed("insufficient_base_on_sell_exchange", opp)

        if opp.execution_style == "maker-taker":
            return self._execute_maker_taker(
                opp=opp,
                route_key=route_key,
                now_ts=now_ts,
                base=base,
                buy_bal=buy_bal,
                sell_bal=sell_bal,
                buy_cost=buy_cost,
            )

        buy_fee = self.config.fees_taker.get(opp.buy_exchange, 0.001)
        sell_fee = self.config.fees_taker.get(opp.sell_exchange, 0.001)
        quote_spent = buy_cost * (1.0 + buy_fee)
        quote_received = (opp.quantity * opp.sell_price) * (1.0 - sell_fee)
        pnl = quote_received - quote_spent
        return self._finalize_execution(
            opp=opp,
            route_key=route_key,
            now_ts=now_ts,
            base=base,
            buy_bal=buy_bal,
            sell_bal=sell_bal,
            quote_spent=quote_spent,
            quote_received=quote_received,
            pnl=pnl,
            reason_ok="ok",
            dry_reason="dry_run_submitted",
            payload=self._build_order_payload(opp),
        )

    def _execute_maker_taker(
        self,
        opp: Opportunity,
        route_key: str,
        now_ts: float,
        base: str,
        buy_bal: ExchangeBalance,
        sell_bal: ExchangeBalance,
        buy_cost: float,
    ) -> TradeResult:
        total_attempts = max(1, 1 + self.config.maker_max_requotes)
        current_fill_probability = _clamp(opp.fill_probability, 0.0, 0.99)
        requotes = 0
        filled = False

        for attempt in range(1, total_attempts + 1):
            timed_out = opp.expected_fill_time_ms > self.config.maker_order_timeout_ms
            if current_fill_probability >= self.config.maker_min_fill_probability and not timed_out:
                filled = True
                break
            if attempt == total_attempts:
                break
            requotes += 1
            self.risk.maker_requotes += 1
            current_fill_probability = _clamp(
                current_fill_probability + self.config.maker_requote_fill_boost,
                0.0,
                0.99,
            )

        if not filled:
            self.risk.maker_timeouts += 1
            self.last_order_payload = self._build_order_payload(
                opp,
                maker_post_only=True,
                maker_timeout_ms=self.config.maker_order_timeout_ms,
                maker_requotes=requotes,
                maker_fill_probability=current_fill_probability,
                maker_result="cancel_timeout",
            )
            return self._register_failure(
                success=False,
                reason="maker_timeout_cancelled",
                symbol=opp.symbol,
                buy_exchange=opp.buy_exchange,
                sell_exchange=opp.sell_exchange,
                quantity=opp.quantity,
                realized_pnl_usdt=0.0,
            )

        buy_fee = opp.buy_fee_pct / 100.0
        sell_fee = opp.sell_fee_pct / 100.0
        quote_spent = buy_cost * (1.0 + buy_fee)
        quote_received = (opp.quantity * opp.sell_price) * (1.0 - sell_fee)
        requote_penalty = buy_cost * (self.config.maker_requote_step_bps / 10000.0) * requotes
        pnl = quote_received - quote_spent - requote_penalty
        if pnl <= 0:
            if not (
                self.mode == "dry-run" and self.config.allow_negative_expected_profit_dryrun
            ):
                return self._register_failure(
                    success=False,
                    reason="requote_eroded_edge",
                    symbol=opp.symbol,
                    buy_exchange=opp.buy_exchange,
                    sell_exchange=opp.sell_exchange,
                    quantity=opp.quantity,
                    realized_pnl_usdt=0.0,
                )

        return self._finalize_execution(
            opp=opp,
            route_key=route_key,
            now_ts=now_ts,
            base=base,
            buy_bal=buy_bal,
            sell_bal=sell_bal,
            quote_spent=quote_spent,
            quote_received=quote_received,
            pnl=pnl,
            reason_ok="maker_taker_ok",
            dry_reason="dry_run_maker_taker_submitted",
            payload=self._build_order_payload(
                opp,
                maker_post_only=True,
                maker_timeout_ms=self.config.maker_order_timeout_ms,
                maker_requotes=requotes,
                maker_fill_probability=current_fill_probability,
                maker_result="filled",
            ),
        )

    def _finalize_execution(
        self,
        opp: Opportunity,
        route_key: str,
        now_ts: float,
        base: str,
        buy_bal: ExchangeBalance,
        sell_bal: ExchangeBalance,
        quote_spent: float,
        quote_received: float,
        pnl: float,
        reason_ok: str,
        dry_reason: str,
        payload: Dict[str, object],
    ) -> TradeResult:
        if self.mode == "dry-run":
            self.last_order_payload = payload
            self.risk.trades_executed += 1
            self.risk.consecutive_failures = 0
            self.last_trade_at[route_key] = now_ts
            logger.info(
                "DRY-RUN ORDER | buy=%s | sell=%s | payload=%s",
                opp.buy_exchange,
                opp.sell_exchange,
                self.last_order_payload,
            )
            return TradeResult(
                success=True,
                reason=dry_reason,
                symbol=opp.symbol,
                buy_exchange=opp.buy_exchange,
                sell_exchange=opp.sell_exchange,
                quantity=opp.quantity,
                realized_pnl_usdt=pnl,
            )

        buy_bal.quote_free -= quote_spent
        buy_bal.base_free[base] = buy_bal.base_free.get(base, 0.0) + opp.quantity
        sell_bal.base_free[base] = sell_bal.base_free.get(base, 0.0) - opp.quantity
        sell_bal.quote_free += quote_received

        self.last_order_payload = payload
        self.risk.realized_pnl_usdt += pnl
        self.risk.trades_executed += 1
        self.risk.consecutive_failures = 0
        self.last_trade_at[route_key] = now_ts
        self._evaluate_drawdown_guard()

        logger.info(
            "PAPER EXECUTED | %s | style=%s | buy=%s @ %.2f | sell=%s @ %.2f | qty=%.6f | pnl=%.4f",
            opp.symbol,
            opp.execution_style,
            opp.buy_exchange,
            opp.buy_price,
            opp.sell_exchange,
            opp.sell_price,
            opp.quantity,
            pnl,
        )

        return TradeResult(
            success=True,
            reason=reason_ok,
            symbol=opp.symbol,
            buy_exchange=opp.buy_exchange,
            sell_exchange=opp.sell_exchange,
            quantity=opp.quantity,
            realized_pnl_usdt=pnl,
        )

    def _evaluate_drawdown_guard(self) -> None:
        total_capital = self.config.capital_per_exchange_usdt * len(self.config.exchanges)
        max_loss = (self.config.max_daily_drawdown_pct / 100.0) * total_capital
        if self.risk.realized_pnl_usdt <= -max_loss:
            self.risk.blocked = True
            self.risk.blocked_reason = "daily_drawdown_limit"
            logger.error(
                "Risk guard activated. Realized PnL %.4f <= -%.4f",
                self.risk.realized_pnl_usdt,
                max_loss,
            )

    def _failed(self, reason: str, opp: Opportunity) -> TradeResult:
        return self._register_failure(
            success=False,
            reason=reason,
            symbol=opp.symbol,
            buy_exchange=opp.buy_exchange,
            sell_exchange=opp.sell_exchange,
            quantity=opp.quantity,
            realized_pnl_usdt=0.0,
        )

    def _register_failure(
        self,
        success: bool,
        reason: str,
        symbol: str,
        buy_exchange: str,
        sell_exchange: str,
        quantity: float,
        realized_pnl_usdt: float,
    ) -> TradeResult:
        self.risk.trades_failed += 1
        self.risk.consecutive_failures += 1

        if self.risk.consecutive_failures >= self.config.max_consecutive_failures:
            self.risk.blocked = True
            self.risk.blocked_reason = "consecutive_failures_limit"
            logger.error(
                "Circuit breaker activated after %d failures.",
                self.risk.consecutive_failures,
            )

        return TradeResult(
            success=False,
            reason=reason,
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            quantity=quantity,
            realized_pnl_usdt=realized_pnl_usdt,
        )

    def rebalance_symbol_inventory(self, symbol: str) -> str | None:
        now_ts = time.time()
        last_ts = self.last_rebalance_at.get(symbol)
        if last_ts is not None and (now_ts - last_ts) < self.config.rebalance_interval_sec:
            return None

        base, _ = symbol.split("/")
        base_by_exchange: Dict[str, float] = {}
        for exchange_name in self.config.exchanges:
            bal = self.balances.get(exchange_name)
            if bal is None:
                continue
            base_by_exchange[exchange_name] = bal.base_free.get(base, 0.0)

        if len(base_by_exchange) < 2:
            return None

        total_base = sum(base_by_exchange.values())
        avg_base = total_base / len(base_by_exchange)
        threshold = avg_base * (self.config.rebalance_threshold_pct / 100.0)
        if threshold <= 0:
            return None

        source = max(base_by_exchange, key=base_by_exchange.get)
        target = min(base_by_exchange, key=base_by_exchange.get)
        source_base = base_by_exchange[source]
        target_base = base_by_exchange[target]

        if (source_base - avg_base) < threshold or (avg_base - target_base) < threshold:
            return None

        transfer_size = min(source_base - avg_base, avg_base - target_base)
        if transfer_size <= 0:
            return None

        source_bal = self.balances[source]
        target_bal = self.balances[target]

        fee = transfer_size * (self.config.rebalance_fee_pct / 100.0)
        net_transfer = transfer_size - fee
        if net_transfer <= 0:
            return None

        source_bal.base_free[base] = source_bal.base_free.get(base, 0.0) - transfer_size
        target_bal.base_free[base] = target_bal.base_free.get(base, 0.0) + net_transfer
        self.last_rebalance_at[symbol] = now_ts

        message = (
            f"Rebalanced {symbol}: {source}->{target} gross={transfer_size:.6f} "
            f"fee={fee:.6f} net={net_transfer:.6f}"
        )
        logger.info(message)
        return message

    def get_metrics(self) -> Dict[str, float | int | str]:
        return {
            "realized_pnl_usdt": self.risk.realized_pnl_usdt,
            "trades_executed": self.risk.trades_executed,
            "trades_failed": self.risk.trades_failed,
            "consecutive_failures": self.risk.consecutive_failures,
            "maker_timeouts": self.risk.maker_timeouts,
            "maker_requotes": self.risk.maker_requotes,
            "blocked": int(self.risk.blocked),
            "blocked_reason": self.risk.blocked_reason,
        }

    def balance_summary(self) -> Dict[str, Dict[str, float]]:
        summary: Dict[str, Dict[str, float]] = {}
        for exchange_name, bal in self.balances.items():
            summary[exchange_name] = {
                "quote_free": round(bal.quote_free, 6),
                "base_total": round(sum(v for v in bal.base_free.values()), 6),
            }
        return summary

    def get_last_order_payload(self) -> Dict[str, object]:
        return dict(self.last_order_payload)

    def _route_key(self, opp: Opportunity) -> str:
        return f"{opp.symbol}:{opp.buy_exchange}->{opp.sell_exchange}"

    def _build_order_payload(
        self,
        opp: Opportunity,
        maker_post_only: bool = False,
        maker_timeout_ms: int = 0,
        maker_requotes: int = 0,
        maker_fill_probability: float = 1.0,
        maker_result: str = "n/a",
    ) -> Dict[str, object]:
        return {
            "buy": {
                "exchange": opp.buy_exchange,
                "symbol": opp.symbol,
                "side": "buy",
                "type": "limit",
                "amount": round(opp.quantity, 8),
                "price": round(opp.buy_price, 6),
                "timeInForce": "PO" if maker_post_only and opp.maker_side == "buy" else "IOC",
                "postOnly": bool(maker_post_only and opp.maker_side == "buy"),
            },
            "sell": {
                "exchange": opp.sell_exchange,
                "symbol": opp.symbol,
                "side": "sell",
                "type": "limit",
                "amount": round(opp.quantity, 8),
                "price": round(opp.sell_price, 6),
                "timeInForce": "PO" if maker_post_only and opp.maker_side == "sell" else "IOC",
                "postOnly": bool(maker_post_only and opp.maker_side == "sell"),
            },
            "meta": {
                "execution_style": opp.execution_style,
                "maker_exchange": opp.maker_exchange,
                "taker_exchange": opp.taker_exchange,
                "maker_side": opp.maker_side,
                "taker_side": opp.taker_side,
                "maker_timeout_ms": maker_timeout_ms,
                "maker_requotes": maker_requotes,
                "maker_fill_probability": round(maker_fill_probability, 4),
                "maker_result": maker_result,
                "dynamic_threshold_pct": round(opp.dynamic_threshold_pct, 6),
                "queue_risk_score": round(opp.queue_risk_score, 6),
                "expected_profit_usdt": round(opp.expected_profit_usdt, 6),
                "net_spread_pct": round(opp.net_spread_pct, 6),
                "buy_price_source": opp.buy_price_source,
                "sell_price_source": opp.sell_price_source,
            },
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
