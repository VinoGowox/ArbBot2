from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    mode: str
    exchanges: list[str]
    symbols: list[str]
    lock: threading.Lock = field(default_factory=threading.Lock)
    data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data = {
            "mode": self.mode,
            "exchanges": self.exchanges,
            "symbols": self.symbols,
            "cycle": 0,
            "last_event": "init",
            "opportunity_count": 0,
            "best_opportunity": None,
          "last_order_payload": {},
            "metrics": {},
            "balances": {},
        }

    def update(self, payload: Dict[str, Any]) -> None:
        with self.lock:
            self.data.update(payload)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.data)


class DashboardServer:
    def __init__(self, host: str, port: int, state: RuntimeState) -> None:
        self._server = _build_server(host, port, state)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info(
            "Dashboard started at http://%s:%d",
            self._server.server_address[0],
            self._server.server_address[1],
        )

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _build_server(host: str, port: int, state: RuntimeState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/metrics.json":
                payload = state.snapshot()
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/" or self.path == "":
                html = _dashboard_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>ArbBot Monitor</title>
  <style>
    :root {
      --bg: #0f1c2f;
      --panel: #112a46;
      --ink: #e9f2ff;
      --muted: #9ec0ea;
      --ok: #2ed198;
      --warn: #ffc857;
      --bad: #ff5d73;
    }
    body {
      margin: 0;
      font-family: 'Segoe UI', Tahoma, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 20% 20%, #214b73, var(--bg));
      min-height: 100vh;
    }
    .wrap {
      max-width: 980px;
      margin: 24px auto;
      padding: 0 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    .card {
      background: linear-gradient(160deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 14px;
      padding: 14px;
    }
    h1 { margin: 0 0 14px; font-size: 24px; }
    .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
    .value { font-size: 22px; margin-top: 6px; }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(0,0,0,0.2);
      border-radius: 10px;
      padding: 10px;
      font-size: 13px;
      color: #d8e8ff;
    }
    .ok { color: var(--ok); }
    .bad { color: var(--bad); }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>ArbBot Monitor</h1>
    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Cycle</div><div id=\"cycle\" class=\"value\">-</div></div>
      <div class=\"card\"><div class=\"label\">Opportunity Count</div><div id=\"opps\" class=\"value\">-</div></div>
      <div class=\"card\"><div class=\"label\">PnL (USDT)</div><div id=\"pnl\" class=\"value\">-</div></div>
      <div class=\"card\"><div class=\"label\">Trades (OK/Fail)</div><div id=\"trades\" class=\"value\">-</div></div>
    </div>
    <div class=\"grid\" style=\"margin-top:12px\">
      <div class=\"card\">
        <div class=\"label\">Last Event</div>
        <div id=\"event\" class=\"value\" style=\"font-size:16px\">-</div>
      </div>
      <div class=\"card\">
        <div class=\"label\">Best Opportunity</div>
        <pre id=\"best\">-</pre>
      </div>
      <div class=\"card\">
        <div class=\"label\">Balances</div>
        <pre id=\"balances\">-</pre>
      </div>
      <div class=\"card\">
        <div class=\"label\">Last Order Payload</div>
        <pre id=\"order\">-</pre>
      </div>
    </div>
  </div>
  <script>
    async function refresh() {
      try {
        const res = await fetch('/metrics.json', { cache: 'no-store' });
        const data = await res.json();
        document.getElementById('cycle').textContent = data.cycle ?? '-';
        document.getElementById('opps').textContent = data.opportunity_count ?? 0;

        const m = data.metrics || {};
        const pnl = Number(m.realized_pnl_usdt || 0).toFixed(4);
        const pnlEl = document.getElementById('pnl');
        pnlEl.textContent = pnl;
        pnlEl.className = 'value ' + (Number(pnl) >= 0 ? 'ok' : 'bad');

        document.getElementById('trades').textContent = `${m.trades_executed || 0} / ${m.trades_failed || 0}`;
        document.getElementById('event').textContent = data.last_event || '-';
        document.getElementById('best').textContent = JSON.stringify(data.best_opportunity || {}, null, 2);
        document.getElementById('balances').textContent = JSON.stringify(data.balances || {}, null, 2);
        document.getElementById('order').textContent = JSON.stringify(data.last_order_payload || {}, null, 2);
      } catch (err) {
        document.getElementById('event').textContent = 'dashboard fetch error';
      }
    }
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>"""
