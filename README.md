# Crypto Arbitrage Bot (Paper Trading First)

Bot ini dirancang untuk menangkap peluang cross-exchange spot arbitrage antara 4 exchange.

- Binance
- Bybit
- OKX
- KuCoin

Fitur utama.

- Scanner multi-exchange untuk BTC/USDT dan ETH/USDT.
- Filter kualitas sinyal berbasis orderbook depth (impact price).
- Kalkulasi net spread dengan taker fee per exchange (resolved dari metadata exchange dengan fallback env) dan slippage dinamis dari depth orderbook.
- Risk controls: daily drawdown limit, min notional, max position, staleness guard.
- Circuit breaker berdasarkan consecutive failures.
- Cooldown per route arbitrage untuk menghindari overtrading.
- Rebalancing inventory base asset antar exchange (simulasi paper).
- Alert Telegram untuk trade, rebalance, dan risk events.
- Dashboard realtime berbasis HTTP untuk monitoring cycle, peluang, dan balance.
- Dashboard menampilkan statistik alasan penolakan peluang per kategori.
- Mode dry-run untuk simulasi payload order semi-live (tanpa kirim order nyata).
- Paper executor dengan pencatatan PnL per trade.
- Siap deploy di cloud (AWS/GCP/Azure) sebagai process service.

## Arsitektur Ringkas

1. ExchangeGateway mengambil ticker dari seluruh exchange.
2. OpportunityEngine menghitung spread bersih yang layak eksekusi.
3. PaperExecutor mensimulasikan buy di exchange A dan sell di exchange B.
4. Risk controls menghentikan eksekusi jika drawdown harian melewati batas.

## Setup

1. Install dependensi.

```bash
pip install -r requirements.txt
```

1. Buat file .env.

```bash
copy .env.example .env
```

1. Jalankan bot.

```bash
python -m src.main
```

## Deploy Google Cloud VM

Panduan deploy production-like (dry-run atau paper) ada di [deploy/GCP_VM_DEPLOY.md](deploy/GCP_VM_DEPLOY.md).

Artefak deploy.

- [deploy/bootstrap_vm.sh](deploy/bootstrap_vm.sh)
- [deploy/install_service.sh](deploy/install_service.sh)
- [deploy/install_logrotate.sh](deploy/install_logrotate.sh)
- [deploy/arbbot.service](deploy/arbbot.service)
- [deploy/arbbot-logrotate](deploy/arbbot-logrotate)
- [deploy/ops.sh](deploy/ops.sh)

## Mode Eksekusi

- MODE=paper: simulasi perpindahan balance antar exchange dan PnL.
- MODE=dry-run: tidak mengubah balance, tetapi membuat payload order buy/sell seolah siap dikirim ke exchange.

## Parameter Penting Untuk Tuning

- MIN_NET_SPREAD_PCT: filter minimum net spread.
- SLIPPAGE_PCT: buffer slippage konservatif.
- USE_DYNAMIC_SLIPPAGE: aktifkan slippage dinamis dari impact orderbook per peluang.
- FEE_TAKER_BINANCE, FEE_TAKER_BYBIT, FEE_TAKER_OKX, FEE_TAKER_KUCOIN: override fee taker per exchange bila ingin memakai angka akun Anda.
- ENABLE_ORDERBOOK_DEPTH: aktifkan perhitungan harga impact dari orderbook.
- REQUIRE_DEPTH_LIQUIDITY: hanya terima sinyal yang punya depth valid.
- ORDERBOOK_IMPACT_NOTIONAL_USDT: ukuran notional simulasi untuk cek kedalaman.
- TRADE_COOLDOWN_SEC: jeda trade pada route yang sama.
- MAX_CONSECUTIVE_FAILURES: trigger circuit breaker.
- MAX_OPPORTUNITY_AGE_MS: batas umur peluang sejak ditemukan scanner.
- REBALANCE_THRESHOLD_PCT: sensitivitas trigger rebalance inventory.
- CAPITAL_PER_TRADE_USDT: sizing per trade.

## Dashboard Realtime

Jika DASHBOARD_ENABLED=true, buka dashboard di [http://127.0.0.1:8080](http://127.0.0.1:8080).

Endpoint JSON.

- /metrics.json

Kategori alasan penolakan yang tampil di dashboard/log antara lain.

- missing_snapshot
- stale_snapshot
- insufficient_fresh_markets
- depth_liquidity_missing
- net_spread_below_threshold
- insufficient_trade_size
- non_positive_expected_profit

## Telegram Alert (Opsional)

Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID pada .env untuk menerima.

- Bot start atau stop.
- Trade executed.
- Inventory rebalance.
- Risk guard blocked event.

## Catatan Penting

- Mode default adalah paper.
- Untuk live trading, butuh hardening tambahan: transfer inventory, retry logic, circuit breaker lanjutan, dan monitoring production.
- Jangan aktifkan izin withdraw pada API key.

## Next Phase (Direkomendasikan)

- Integrasi websocket market data untuk latensi lebih rendah.
- Smart inventory rebalancing per exchange.
- Strategy optimizer per pair berbasis volatility regime.
- Notifikasi Telegram atau Discord untuk event penting.
