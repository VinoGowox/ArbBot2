# ArbBot Deploy Guide for Google Cloud VM

## 1. Recommended VM Spec

- OS: Ubuntu 22.04 LTS.
- Machine: e2-small atau lebih tinggi.
- Disk: 20 GB persistent disk.
- Network tags: allow ssh, optional dashboard access hanya dari trusted IP.

## 2. Initial Server Hardening

Run pada VM.

```bash
sudo apt-get update
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

Optional firewall.

```bash
sudo apt-get install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp
sudo ufw enable
```

Jika Anda memang ingin dashboard terbuka untuk semua IP, gunakan rule di atas.
Tetap disarankan memakai mode dry-run atau paper saat dashboard public.

## 3. Copy Project to VM

Opsi A, tanpa gcloud di local: clone langsung dari VM (direkomendasikan).

```bash
sudo mkdir -p /opt/arbbot
sudo git clone <PRIVATE_REPO_URL> /opt/arbbot/app
```

Opsi B, tanpa GitHub dan tanpa gcloud di local: upload zip via SFTP (WinSCP/FileZilla) ke VM, lalu extract.

```bash
sudo apt-get install -y unzip
sudo mkdir -p /opt/arbbot/app
sudo unzip /tmp/arbbot.zip -d /opt/arbbot/app
```

Opsi C, jika scp OpenSSH tersedia di Windows local.

```bash
scp -i <PATH_KEY> -r <LOCAL_PROJECT_DIR> <VM_USER>@<VM_EXTERNAL_IP>:/tmp/arbbot
sudo mkdir -p /opt/arbbot
sudo mv /tmp/arbbot /opt/arbbot/app
```

Jika Anda punya gcloud di mesin tertentu, ini tetap valid.

```bash
gcloud compute scp --recurse . <VM_NAME>:/tmp/arbbot --zone <ZONE>
```

Di VM.

```bash
sudo mkdir -p /opt/arbbot
sudo mv /tmp/arbbot /opt/arbbot/app
sudo chown -R root:root /opt/arbbot/app
```

Catatan zona Jakarta: umumnya menggunakan format zone seperti asia-southeast2-a.
Jika tidak yakin zone instance, cek dari VM:

```bash
curl -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/zone
```

## 4. Bootstrap Runtime

Di VM, masuk ke project root.

```bash
cd /opt/arbbot/app
sudo bash deploy/bootstrap_vm.sh
```

Lalu edit environment.

```bash
sudo nano /opt/arbbot/app/.env
```

Minimum settings untuk staging.

- MODE=dry-run
- DASHBOARD_ENABLED=true
- DASHBOARD_HOST=0.0.0.0
- DASHBOARD_PORT=8080
- TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID jika dipakai.

## 5. Install and Start Service

```bash
cd /opt/arbbot/app
sudo bash deploy/install_service.sh
sudo bash deploy/install_logrotate.sh
```

Check service.

```bash
systemctl status arbbot.service --no-pager
journalctl -u arbbot.service -n 200 --no-pager
```

## 6. Expose Dashboard Safely

Lebih aman memakai tunnel daripada public access.

```bash
gcloud compute ssh <VM_NAME> --zone <ZONE> -- -L 8080:127.0.0.1:8080
```

Buka di browser lokal: [http://127.0.0.1:8080](http://127.0.0.1:8080)

## 7. Update Workflow

Saat kode berubah.

```bash
cd /opt/arbbot/app
sudo -u arbbot /opt/arbbot/app/.venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart arbbot.service
```

## 8. Operational Commands

Pakai helper script.

```bash
cd /opt/arbbot/app
bash deploy/ops.sh status
bash deploy/ops.sh logs
bash deploy/ops.sh restart
```

## 9. Go-Live Checklist (After Staging)

- Run dry-run minimal 5 sampai 7 hari tanpa crash.
- Pastikan konektivitas stabil ke semua exchange.
- Verifikasi stale opportunity guard dan circuit breaker muncul di log saat kondisi terpicu.
- Gunakan API key khusus trading, tanpa permission withdraw.

## 10. Rollback and Stop

```bash
sudo systemctl stop arbbot.service
sudo systemctl disable arbbot.service
```
