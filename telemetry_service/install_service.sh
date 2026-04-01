#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="gpanel-telemetry"
INSTALL_DIR="${HOME}/gpanel-telemetry"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

mkdir -p "${INSTALL_DIR}"
cp telemetry_server.py "${INSTALL_DIR}/"

cat > "${INSTALL_DIR}/.env" <<'ENVEOF'
TELEMETRY_HOST=127.0.0.1
TELEMETRY_PORT=8787
TELEMETRY_DB_PATH=
ENVEOF

sudo tee "${SERVICE_FILE}" > /dev/null <<EOF
[Unit]
Description=G-PANEL Telemetry Service
After=network.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=-${INSTALL_DIR}/.env
ExecStart=/usr/bin/env python3 ${INSTALL_DIR}/telemetry_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager
