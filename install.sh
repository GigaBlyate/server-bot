#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

REPO_URL="https://github.com/GigaBlyate/server-bot.git"
INSTALL_DIR="${HOME}/server-bot"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_NAME="server-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
MANAGER_PATH="/usr/local/bin/bot"
ROOT_HELPER_PATH="/usr/local/bin/server-bot-rootctl"
SUDOERS_FILE="/etc/sudoers.d/server-bot-$(id -un)"
TELEMETRY_URL_FIXED="https://g-panel.top"
LOG_DIR="/var/log/server-bot"
BOT_USER="$(id -un)"
BOT_GROUP="$(id -gn)"
LOG_FILE="${HOME}/install-bot.log"
ERROR_LOG="${HOME}/install-bot-errors.log"

SYSTEM_PACKAGES=(
  git curl wget rsync ca-certificates sudo
  python3 python3-pip python3-venv python3-dotenv
  sqlite3 openssl iputils-ping dnsutils pciutils
  lsb-release tar
)

print_sep() { printf '\n============================================================\n'; }
print_step() { print_sep; echo "[STEP $1] $2"; print_sep; }
print_info() { echo "[INFO] $*" | tee -a "$LOG_FILE"; }
print_ok() { echo "[ OK ] $*" | tee -a "$LOG_FILE"; }
print_warn() { echo "[WARN] $*" | tee -a "$ERROR_LOG"; }
print_fail() { echo "[FAIL] $*" | tee -a "$ERROR_LOG" >&2; }

die() {
  print_fail "$*"
  exit 1
}

ask_tty() {
  local prompt="$1"
  local __resultvar="$2"
  local reply=""
  read -r -p "$prompt" reply </dev/tty
  printf -v "$__resultvar" '%s' "$reply"
}

ask_yes_no() {
  local prompt="$1"
  local __resultvar="$2"
  local reply=""
  while true; do
    read -r -p "$prompt [y/n]: " reply </dev/tty
    reply="$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]' | xargs)"
    case "$reply" in
      y|yes|д|да) printf -v "$__resultvar" 'true'; return 0 ;;
      n|no|н|нет) printf -v "$__resultvar" 'false'; return 0 ;;
      *) echo "Введите y или n." ;;
    esac
  done
}

require_non_root() {
  [[ "$EUID" -ne 0 ]] || die "Запускайте установщик от обычного пользователя, не от root."
}

require_sudo() {
  command -v sudo >/dev/null 2>&1 || die "sudo не найден"
  sudo -v || die "Нужны права sudo"
}

ensure_packages() {
  print_step 1 "Проверяю системные пакеты"
  sudo DEBIAN_FRONTEND=noninteractive apt-get update >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось обновить список пакетов"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${SYSTEM_PACKAGES[@]}" >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось установить обязательные системные пакеты"
  print_ok "Проверка и установка системных пакетов завершены"
}

show_install_terms() {
  print_step 2 "Условия установки"
  echo "Устанавливая G-PANEL, вы соглашаетесь на отправку анонимной статистики на ${TELEMETRY_URL_FIXED}."
  echo "Это используется только для честных счётчиков установок, активных ботов и актуальной версии на сайте."
  echo
  local consent="false"
  ask_yes_no "Продолжить установку?" consent
  [[ "$consent" == "true" ]] || die "Установка отменена пользователем"
}

prepare_install_dir() {
  print_step 3 "Подготавливаю каталог установки"
  mkdir -p "$INSTALL_DIR"
  print_ok "Каталог установки готов"
}

clone_repo() {
  print_step 4 "Получаю код проекта"
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    print_info "Репозиторий уже существует, обновляю"
    git -C "$INSTALL_DIR" fetch --all >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось обновить git-репозиторий"
    git -C "$INSTALL_DIR" reset --hard origin/main >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось обновить код проекта"
  else
    rm -rf "$INSTALL_DIR"
    print_info "Клонирую ${REPO_URL}"
    git clone --depth 1 --branch main "$REPO_URL" "$INSTALL_DIR" >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось клонировать репозиторий"
  fi
  print_ok "Код успешно получен из GitHub"
}

setup_python() {
  print_step 5 "Настраиваю Python и зависимости"
  print_info "Создаю виртуальное окружение"
  python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось создать виртуальное окружение"
  print_info "Обновляю pip"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось обновить pip"
  print_info "Устанавливаю Python-зависимости"
  "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось установить Python-зависимости"
  print_ok "Python-зависимости установлены"
}

setup_env() {
  print_step 6 "Настраиваю .env"
  echo "Сейчас будут заполнены основные настройки бота."
  echo "TELEMETRY_URL будет жёстко установлен на ${TELEMETRY_URL_FIXED}."
  echo
  local bot_token=""
  local admin_id=""
  local server_name=""
  ask_tty "Введите BOT_TOKEN от BotFather: " bot_token
  ask_tty "Введите ADMIN_ID администратора Telegram: " admin_id
  ask_tty "Введите SERVER_NAME [MyVPS]: " server_name
  server_name="${server_name:-MyVPS}"

  cat > "$INSTALL_DIR/.env" <<ENV
BOT_TOKEN=${bot_token}
ADMIN_ID=${admin_id}
SERVER_NAME=${server_name}
TELEMETRY_URL=${TELEMETRY_URL_FIXED}
TELEMETRY_ENABLED=true
LOG_LEVEL=INFO
ENV
  chmod 600 "$INSTALL_DIR/.env"
  print_ok ".env заполнен"
}

setup_logs() {
  print_step 7 "Настраиваю логи и права"
  sudo mkdir -p "$LOG_DIR"
  sudo chown -R "$BOT_USER:$BOT_GROUP" "$LOG_DIR"
  sudo chown -R "$BOT_USER:$BOT_GROUP" "$INSTALL_DIR"
  print_ok "Каталог логов готов"
}

create_root_helper() {
  sudo tee "$ROOT_HELPER_PATH" >/dev/null <<'ROOTCTL'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
cmd="${1:-}"
shift || true
case "$cmd" in
  status)
    systemctl status "$@"
    ;;
  restart)
    systemctl restart "$@"
    ;;
  stop)
    systemctl stop "$@"
    ;;
  start)
    systemctl start "$@"
    ;;
  logs)
    journalctl "$@"
    ;;
  *)
    echo "Unsupported action" >&2
    exit 2
    ;;
esac
ROOTCTL
  sudo chmod 755 "$ROOT_HELPER_PATH"
}

setup_manager() {
  print_step 8 "Устанавливаю консольное меню bot"
  create_root_helper
  sudo tee "$MANAGER_PATH" >/dev/null <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
while true; do
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
  read -r -p "Ваш выбор (1-9): " choice
  case "\$choice" in
    1) sudo "$ROOT_HELPER_PATH" restart "$SERVICE_NAME" ;;
    2) sudo "$ROOT_HELPER_PATH" stop "$SERVICE_NAME" ;;
    3)
      read -r -p "Точно удалить бота? [y/n]: " ans
      if [[ "\${ans,,}" =~ ^(y|yes|д|да)$ ]]; then
        sudo systemctl stop "$SERVICE_NAME" || true
        sudo systemctl disable "$SERVICE_NAME" || true
        sudo rm -f "$SERVICE_FILE"
        sudo systemctl daemon-reload || true
        rm -rf "$INSTALL_DIR"
        sudo rm -f "$MANAGER_PATH" "$ROOT_HELPER_PATH" "$SUDOERS_FILE"
        echo "Бот удалён"
        exit 0
      fi
      ;;
    4)
      mkdir -p "$INSTALL_DIR/backups"
      tar -czf "$INSTALL_DIR/backups/server-bot-backup-\$(date +%F-%H%M%S).tar.gz" -C "$INSTALL_DIR" .
      echo "Бэкап создан"
      ;;
    5)
      curl -fsSL https://raw.githubusercontent.com/GigaBlyate/server-bot/main/install.sh | bash
      exit 0
      ;;
    6)
      cd "$INSTALL_DIR"
      "$VENV_DIR/bin/python" -m py_compile bot.py core/*.py handlers/*.py services/*.py ui/*.py >/dev/null
      echo "Проверка завершена"
      ;;
    7) sudo journalctl -u "$SERVICE_NAME" -f ;;
    8) sudo "$ROOT_HELPER_PATH" status "$SERVICE_NAME" ;;
    9) exit 0 ;;
    *) echo "Неверный выбор" ;;
  esac
  echo
  read -r -p "Нажмите Enter для продолжения..." _
  clear || true
done
EOF
  sudo chmod 755 "$MANAGER_PATH"
  sudo tee "$SUDOERS_FILE" >/dev/null <<EOF
$BOT_USER ALL=(root) NOPASSWD: $ROOT_HELPER_PATH
$BOT_USER ALL=(root) NOPASSWD: /bin/systemctl * $SERVICE_NAME*
$BOT_USER ALL=(root) NOPASSWD: /bin/journalctl * $SERVICE_NAME*
EOF
  sudo chmod 440 "$SUDOERS_FILE"
  print_ok "Команда 'bot' установлена"
}

setup_systemd() {
  print_step 9 "Создаю systemd сервис"
  sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Server Management Bot by GigaBlyate
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
Group=$BOT_GROUP
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
Environment=TELEMETRY_URL=$TELEMETRY_URL_FIXED
Environment=BOT_ROOT_HELPER=$ROOT_HELPER_PATH
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/bot.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
UMask=0077
PrivateTmp=true
ProtectHome=read-only
ReadWritePaths=$INSTALL_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME" >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось включить сервис"
  print_ok "systemd сервис создан"
}

verify_files() {
  print_step 10 "Проверяю целостность файлов"
  cd "$INSTALL_DIR"
  "$VENV_DIR/bin/python" -m py_compile bot.py core/*.py handlers/*.py services/*.py ui/*.py >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Проверка Python-файлов не прошла"
  print_ok "Проверка Python-файлов прошла успешно"
}

start_service() {
  print_step 11 "Запускаю бота"
  sudo systemctl restart "$SERVICE_NAME" >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось запустить systemd сервис"
  sleep 2
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
  print_ok "Бот запущен"
}

main() {
  : > "$LOG_FILE"
  : > "$ERROR_LOG"
  require_non_root
  require_sudo
  ensure_packages
  show_install_terms
  prepare_install_dir
  clone_repo
  setup_python
  setup_env
  setup_logs
  setup_manager
  setup_systemd
  verify_files
  start_service
  print_ok "Установка завершена. Откройте Telegram и используйте /start"
  print_info "Для локального управления используйте команду: bot"
}

main "$@"
