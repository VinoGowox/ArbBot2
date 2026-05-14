from __future__ import annotations

import logging
import signal
import time
from dataclasses import asdict

from .config import load_config
from .dashboard import DashboardServer, RuntimeState
from .executor import PaperExecutor
from .exchanges import ExchangeGateway
from .logging_setup import setup_logging
from .notifier import TelegramNotifier
from .opportunity import OpportunityEngine

logger = logging.getLogger(__name__)
STOP = False


def _request_stop(signum, _frame) -> None:  # type: ignore[no-untyped-def]
    global STOP
    STOP = True
    logger.warning("Stop signal received: %s", signum)


def run() -> None:
    setup_logging()
    cfg = load_config()

    if cfg.mode not in {"paper", "dry-run"}:
        logger.warning("Unsupported MODE=%s. Falling back to MODE=paper.", cfg.mode)
        cfg.mode = "paper"

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    gateway = ExchangeGateway(cfg)
    engine = OpportunityEngine(cfg)
    executor = PaperExecutor(cfg)
    notifier = TelegramNotifier(cfg)
    runtime = RuntimeState(cfg.mode, cfg.exchanges, cfg.symbols)
    dashboard = None
    last_status_ts = 0.0
    blocked_alert_sent = False

    if cfg.dashboard_enabled:
        try:
            dashboard = DashboardServer(cfg.dashboard_host, cfg.dashboard_port, runtime)
            dashboard.start()
        except OSError as exc:
            logger.error(
                "Dashboard disabled. Failed to bind %s:%d | %s",
                cfg.dashboard_host,
                cfg.dashboard_port,
                exc,
            )
            dashboard = None

    logger.info(
        "Bot started | exchanges=%s | symbols=%s | min_net_spread=%.4f%%",
        cfg.exchanges,
        cfg.symbols,
        cfg.min_net_spread_pct,
    )
    if notifier.enabled:
        notifier.send(
            f"ArbBot started in {cfg.mode} mode | symbols={','.join(cfg.symbols)}"
        )

    cycles = 0
    try:
        while not STOP:
            cycles += 1
            market = gateway.fetch_all_tickers(cfg.symbols)
            opportunities = engine.find_opportunities(market)
            rejection_stats = engine.get_rejection_counts()
            spread_dist = engine.get_net_spread_distribution()
            runtime.update(
                {
                    "cycle": cycles,
                    "opportunity_count": len(opportunities),
                    "last_event": "scan_completed",
                    "rejections_last_cycle": rejection_stats["last_cycle"],
                    "rejections_total": rejection_stats["total"],
                    "net_spread_distribution": spread_dist,
                }
            )

            if opportunities:
                attempts = opportunities[: max(1, cfg.max_opportunities_per_cycle)]
                executed = False
                runtime.update({"best_opportunity": asdict(opportunities[0])})
                for opp in attempts:
                    age_ms = int(time.time() * 1000) - opp.timestamp_ms
                    if age_ms > cfg.max_opportunity_age_ms:
                        runtime.update({"last_event": f"opportunity_stale:{age_ms}ms"})
                        continue

                    result = executor.execute(opp)
                    if result.success:
                        executed = True
                        runtime.update(
                            {
                                "last_event": result.reason,
                                "last_order_payload": executor.get_last_order_payload(),
                            }
                        )
                        logger.info(
                            "Cycle %d | executed | mode=%s | expected=%.4f USDT | net_spread=%.4f%% | source=%s/%s",
                            cycles,
                            cfg.mode,
                            opp.expected_profit_usdt,
                            opp.net_spread_pct,
                            opp.buy_price_source,
                            opp.sell_price_source,
                        )
                        if notifier.enabled:
                            notifier.send(
                                "Trade executed | "
                                f"{opp.symbol} {opp.buy_exchange}->{opp.sell_exchange} "
                                f"qty={opp.quantity:.6f} est={opp.expected_profit_usdt:.4f}"
                            )
                        break

                if not executed:
                    runtime.update({"last_event": "no_executable_route"})
                    logger.info("Cycle %d | skipped | no executable route", cycles)
            else:
                runtime.update({"best_opportunity": None, "last_event": "no_opportunity"})
                logger.debug("Cycle %d | no valid opportunities", cycles)

            for symbol in cfg.symbols:
                rebalance_message = executor.rebalance_symbol_inventory(symbol)
                if rebalance_message and notifier.enabled:
                    notifier.send(rebalance_message)
                if rebalance_message:
                    runtime.update({"last_event": rebalance_message})

            if executor.risk.blocked and notifier.enabled and not blocked_alert_sent:
                notifier.send(f"ArbBot blocked by risk guard: {executor.risk.blocked_reason}")
                blocked_alert_sent = True

            now_ts = time.time()
            if (now_ts - last_status_ts) >= cfg.status_log_interval_sec:
                metrics = executor.get_metrics()
                runtime.update(
                    {
                        "metrics": metrics,
                        "balances": executor.balance_summary(),
                    }
                )
                logger.info(
                    "Status | pnl=%.4f | ok=%d | fail=%d | streak=%d | blocked=%d(%s) | reject_last=%s | spread_dist=%s",
                    metrics["realized_pnl_usdt"],
                    metrics["trades_executed"],
                    metrics["trades_failed"],
                    metrics["consecutive_failures"],
                    metrics["blocked"],
                    metrics["blocked_reason"],
                    rejection_stats["last_cycle"],
                    spread_dist,
                )
                last_status_ts = now_ts

            time.sleep(cfg.poll_interval_sec)
    finally:
        gateway.close()
        if dashboard is not None:
            dashboard.stop()
        if notifier.enabled:
            notifier.send("ArbBot stopped")
        logger.info("Bot stopped.")


if __name__ == "__main__":
    run()
