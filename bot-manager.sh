#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/home/gigablyate/server-bot"
SERVICE="server-bot"
TELEMETRY_URL="https://g-panel.top"
ROOT_HELPER="/usr/local/bin/server-bot-rootctl"

send_uninstall() {
  local py="${INSTALL_DIR}/venv/bin/python"
  if [[ -x "$py" && -f "${INSTALL_DIR}/telemetry_ctl.py" ]]; then
    TELEMETRY_URL="${TELEMETRY_URL}" "$py" "${INSTALL_DIR}/telemetry_ctl.py" uninstall >/dev/null 2>&1 || true
  fi
}

backup_bot() {
  local ts backup_dir archive
  ts="$(date +%Y%m%d-%H%M%S)"
  backup_dir="${HOME}/server-bot-manual-backups"
  archive="${backup_dir}/server-bot-${ts}.tar.gz"
  mkdir -p "$backup_dir"
  tar -czf "$archive" -C "$INSTALL_DIR" .env config.py vps_data.db oauth-credentials.json token.pickle backups 2>/dev/null || true
  echo "Бэкап создан: $archive"
  read -r -p "Нажмите Enter для продолжения..." _
}

integrity_check() {
  source "${INSTALL_DIR}/venv/bin/activate"
  python -m compileall "${INSTALL_DIR}" >/dev/null
  echo "Проверка Python-файлов завершена успешно."
  read -r -p "Нажмите Enter для продолжения..." _
}

update_bot() {
  cd "$INSTALL_DIR"
  git fetch --all && git reset --hard origin/main
  source "${INSTALL_DIR}/venv/bin/activate"
  pip install -r requirements.txt
  sudo "$ROOT_HELPER" restart-bot
  echo "Бот обновлён и перезапущен."
  read -r -p "Нажмите Enter для продолжения..." _
}

while true; do
  clear
  echo "==============================================="
  echo "             G-PANEL BOT MANAGER               "
  echo "==============================================="
  echo "1) Перезапустить бота"
  echo "2) Остановить бота"
  echo "3) Полностью удалить бота"
  echo "4) Сделать бэкап бота"
  echo "5) Обновить бота"
  echo "6) Проверить целостность файлов"
  echo "7) Логи в реальном времени"
  echo "8) Статус сервиса"
  echo "9) Выход"
  echo
  read -r -p "Ваш выбор (1-9): " action
  case "$action" in
    1) sudo "$ROOT_HELPER" restart-bot; sudo systemctl --no-pager status "$SERVICE"; read -r -p "Нажмите Enter..." _ ;;
    2) sudo systemctl stop "$SERVICE"; echo "Бот остановлен"; read -r -p "Нажмите Enter..." _ ;;
    3)
      read -r -p "Точно удалить бота? [y/n]: " confirm
      if [[ "$confirm" =~ ^[Yy]$ ]]; then
        send_uninstall
        sudo systemctl stop "$SERVICE" || true
        sudo systemctl disable "$SERVICE" || true
        sudo rm -f /etc/systemd/system/server-bot.service /etc/sudoers.d/server-bot-$(id -un) /usr/local/bin/bot /usr/local/bin/server-bot-rootctl
        sudo systemctl daemon-reload
        rm -rf "$INSTALL_DIR"
        echo "Бот удалён"
        exit 0
      fi
      ;;
    4) backup_bot ;;
    5) update_bot ;;
    6) integrity_check ;;
    7) sudo journalctl -u "$SERVICE" -f ;;
    8) sudo systemctl --no-pager status "$SERVICE"; read -r -p "Нажмите Enter..." _ ;;
    9) exit 0 ;;
    *) echo "Неверный выбор"; sleep 1 ;;
  esac
done
