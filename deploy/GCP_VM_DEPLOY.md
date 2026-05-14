# ArbBot Deploy Guide for Google Cloud VM (Complete)

Panduan ini untuk Ubuntu 22.04 fresh VM, sesuai kebutuhan Anda.

## A. Prinsip Eksekusi Command

- Gunakan user biasa untuk login SSH harian.
- Gunakan sudo hanya saat butuh hak admin (install package, systemd, firewall, file di /opt).
- Bot dijalankan oleh service user non-login bernama arbbot.
- Jangan jalankan bot sebagai root.

## B. Prasyarat

- VM aktif, bisa SSH.
- Source code sudah ada di GitHub: [VinoGowox/ArbBot2](https://github.com/VinoGowox/ArbBot2)
- Python 3.10+ tersedia (akan di-install di langkah berikut).

## C. Step 1 - Login ke VM

```bash
gcloud compute ssh arb2 --zone asia-southeast2-a
```

Jika zone berbeda, cek cepat dari VM:

```bash
curl -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/zone
```

## D. Step 2 - Update OS dan Paket Dasar

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
  git curl ca-certificates unzip \
  python3 python3-venv python3-pip \
  unattended-upgrades ufw
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

## E. Step 3 - Firewall (Dashboard Public)

Sesuai permintaan Anda, dashboard dibuka ke semua IP.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp
sudo ufw --force enable
sudo ufw status
```

Di GCP, UFW saja tidak cukup. Tambahkan juga VPC firewall rule (sekali saja).

```bash
gcloud compute firewall-rules create arbbot-allow-8080 \
  --allow=tcp:8080 \
  --direction=INGRESS \
  --priority=1000 \
  --source-ranges=0.0.0.0/0
```

## F. Step 4 - Ambil Source Code

### Opsi direkomendasikan: clone langsung di VM

```bash
sudo mkdir -p /opt/arbbot
sudo git clone https://github.com/VinoGowox/ArbBot2.git /opt/arbbot/app
```

Jika folder sudah ada karena deploy sebelumnya:

```bash
cd /opt/arbbot/app
sudo chown -R arbbot:arbbot /opt/arbbot/app
sudo -u arbbot git -C /opt/arbbot/app pull
```

## G. Step 5 - Bootstrap Runtime

```bash
cd /opt/arbbot/app
sudo bash deploy/bootstrap_vm.sh
```

Yang dilakukan script ini:

- install dependency runtime,
- buat service user arbbot,
- buat virtualenv,
- install requirements,
- buat .env awal dari .env.example jika belum ada.

## H. Step 6 - Konfigurasi .env

```bash
sudo nano /opt/arbbot/app/.env
```

Isi minimum untuk staging:

```dotenv
MODE=dry-run
EXCHANGES=binance,bybit,okx,kucoin
SYMBOLS=BTC/USDT,ETH/USDT

DASHBOARD_ENABLED=true
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8080

# Optional
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Simpan file, lalu set permission aman:

```bash
sudo chown arbbot:arbbot /opt/arbbot/app/.env
sudo chmod 640 /opt/arbbot/app/.env
```

## I. Step 7 - Install dan Jalankan Service

```bash
cd /opt/arbbot/app
sudo bash deploy/install_service.sh
sudo bash deploy/install_logrotate.sh
```

## J. Step 8 - Verifikasi Service

```bash
systemctl status arbbot.service --no-pager -l
journalctl -u arbbot.service -n 200 --no-pager
```

Health check cepat:

```bash
curl -s http://127.0.0.1:8080/metrics.json | head
```

Dari browser luar VM:

- http://<EXTERNAL_IP_VM>:8080

## K. Step 9 - Operasional Harian

```bash
cd /opt/arbbot/app
bash deploy/ops.sh status
bash deploy/ops.sh logs
bash deploy/ops.sh restart
```

## L. Step 10 - Update Kode Tanpa Reinstall Total

```bash
cd /opt/arbbot/app
sudo chown -R arbbot:arbbot /opt/arbbot/app
sudo -u arbbot git -C /opt/arbbot/app pull
sudo -u arbbot /opt/arbbot/app/.venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart arbbot.service
systemctl status arbbot.service --no-pager -l
```

## M. Troubleshooting Wajib

### 1) Service aktif tapi warning permission git config

Jika ada warning /home/arbbot/.config/git, update ke versi service terbaru lalu reinstall:

```bash
cd /opt/arbbot/app
sudo chown -R arbbot:arbbot /opt/arbbot/app
sudo -u arbbot git -C /opt/arbbot/app pull
sudo bash deploy/install_service.sh
sudo systemctl restart arbbot.service
journalctl -u arbbot.service -n 50 --no-pager
```

### 2) ModuleNotFoundError (contoh dotenv)

Pastikan service pakai venv bawaan app:

```bash
sudo -u arbbot /opt/arbbot/app/.venv/bin/python -m pip install -r /opt/arbbot/app/requirements.txt
sudo systemctl restart arbbot.service
```

### 3) Dashboard tidak bisa diakses dari luar

- Pastikan .env berisi DASHBOARD_HOST=0.0.0.0
- Pastikan UFW allow 8080/tcp
- Pastikan firewall rule GCP mengizinkan tcp:8080

Cek listening port:

```bash
sudo ss -ltnp | grep 8080
```

### 4) Service crash loop

```bash
journalctl -u arbbot.service -n 300 --no-pager
```

Lalu validasi syntax cepat:

```bash
cd /opt/arbbot/app
sudo -u arbbot /opt/arbbot/app/.venv/bin/python -m compileall src
```

### 5) PermissionError [Errno 13] saat bind dashboard

Error tipikal:

```text
PermissionError: [Errno 13] Permission denied
```

Langkah cek cepat:

```bash
grep -E '^DASHBOARD_(HOST|PORT)=' /opt/arbbot/app/.env
```

Pastikan:

- DASHBOARD_HOST=0.0.0.0 atau 127.0.0.1
- DASHBOARD_PORT=8080 (atau port >1024)

Jika Anda memakai port <1024 (misalnya 80), user non-root akan gagal bind.
Paling aman: ubah ke 8080, lalu restart service.

```bash
sudo systemctl restart arbbot.service
journalctl -u arbbot.service -n 80 --no-pager
```

## N. Go-Live Checklist

- Dry-run 5-7 hari tanpa crash.
- Log stabil, tidak ada error berulang.
- Risk guard, cooldown, stale guard tervalidasi.
- API key trading tanpa izin withdraw.
- Gunakan MODE=paper hanya untuk simulasi lebih ketat; live trading butuh executor live terpisah.
