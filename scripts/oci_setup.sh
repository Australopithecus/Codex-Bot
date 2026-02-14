#!/usr/bin/env bash
set -euo pipefail

APP_USER="$(id -un)"
APP_DIR="$HOME/broker-bot"
TZ_NAME="America/New_York"

if [ ! -d "$APP_DIR" ]; then
  echo "Expected repo at $APP_DIR. Copy the project there first."
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip ufw

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.bot.txt"

"$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/setup_env.py"

# Set timezone to Eastern (adjust if you want fixed EST without DST)
sudo timedatectl set-timezone "$TZ_NAME"

# Firewall: allow SSH + dashboard port
sudo ufw allow OpenSSH
sudo ufw allow 8000/tcp
sudo ufw --force enable

# Systemd service for dashboard
sudo tee /etc/systemd/system/brokerbot-dashboard.service >/dev/null <<UNIT
[Unit]
Description=Broker Bot Dashboard
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=DASHBOARD_HOST=0.0.0.0
Environment=DASHBOARD_PORT=8000
ExecStart=$APP_DIR/.venv/bin/python -m broker_bot.cli dashboard-web
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# Systemd service + timer for advisor
sudo tee /etc/systemd/system/brokerbot-advisor.service >/dev/null <<UNIT
[Unit]
Description=Broker Bot Advisor Report
After=network.target

[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m broker_bot.cli advisor-report
UNIT

sudo tee /etc/systemd/system/brokerbot-advisor.timer >/dev/null <<UNIT
[Unit]
Description=Run Broker Bot Advisor weekdays at 4:15pm ET

[Timer]
OnCalendar=Mon..Fri 16:15
Persistent=true

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now brokerbot-dashboard.service
sudo systemctl enable --now brokerbot-advisor.timer

echo "Setup complete. Dashboard should be on port 8000."
