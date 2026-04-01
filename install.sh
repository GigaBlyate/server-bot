#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

REPO="GigaBlyate/server-bot"
REPO_URL="https://github.com/GigaBlyate/server-bot"
REPO_GIT_URL="${REPO_URL}.git"
REPO_TARBALL_URL="https://codeload.github.com/GigaBlyate/server-bot/tar.gz/refs/heads/main"
INSTALL_DIR="${HOME}/server-bot"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_NAME="server-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SUDOERS_FILE="/etc/sudoers.d/server-bot-$(id -un)"
MANAGER_PATH="/usr/local/bin/bot"
ROOT_HELPER_PATH="/usr/local/bin/server-bot-rootctl"
LOG_FILE="${HOME}/install-bot.log"
ERROR_LOG="${HOME}/install-bot-errors.log"
TELEMETRY_URL_FIXED="https://g-panel.top"
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
TMP_BACKUP_DIR=""
MODE=""

PROTECTED_FILES=(
  ".env"
  "config.py"
  "vps_data.db"
  "oauth-credentials.json"
  "token.pickle"
)
PROTECTED_DIRS=("backups")
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

cleanup() {
  local code=$?
  if [[ -n "$TMP_BACKUP_DIR" && -d "$TMP_BACKUP_DIR" ]]; then
    rm -rf "$TMP_BACKUP_DIR" || true
  fi
  exit "$code"
}
trap cleanup EXIT

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

check_dpkg_health() {
  local audit_out=""
  audit_out="$(sudo dpkg --audit 2>&1 || true)"
  if [[ -n "$audit_out" ]]; then
    print_fail "На сервере обнаружено незавершённое состояние dpkg."
    echo "$audit_out" | tee -a "$ERROR_LOG" >&2
    echo "Выполните команды и повторите установку:" >&2
    echo "  sudo dpkg --configure -a" >&2
    echo "  sudo apt -f install" >&2
    exit 1
  fi
}

ensure_packages() {
  print_step 1 "Проверяю системные пакеты"
  check_dpkg_health

  sudo DEBIAN_FRONTEND=noninteractive apt-get update >> "$LOG_FILE" 2>> "$ERROR_LOG" || \
    die "Не удалось обновить список пакетов"

  local missing=()
  local present=()
  local pkg=""
  for pkg in "${SYSTEM_PACKAGES[@]}"; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
      present+=("$pkg")
    else
      missing+=("$pkg")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    print_info "Устанавливаю отсутствующие пакеты: ${missing[*]}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}" >> "$LOG_FILE" 2>> "$ERROR_LOG" || \
      die "Не удалось установить обязательные системные пакеты"
  else
    print_ok "Все обязательные пакеты уже установлены"
  fi

  if (( ${#present[@]} > 0 )); then
    print_info "Проверяю обновления для уже установленных пакетов"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --only-upgrade "${present[@]}" >> "$LOG_FILE" 2>> "$ERROR_LOG" || \
      die "Не удалось обновить системные пакеты. Сначала исправьте apt/dpkg и повторите установку"
  fi

  check_dpkg_health
  print_ok "Проверка и обновление системных пакетов завершены"
}

show_agreement() {
  cat <<AGREEMENT
Соглашение об анонимной статистике:
- отправляются только server_uid, install_id, текущая версия бота и heartbeat активности;
- НЕ отправляются IP-адрес, hostname, домены, токены, содержимое конфигов, сообщения и бэкапы;
- server_uid — анонимный технический идентификатор одного и того же сервера;
- статистика нужна только для честных счётчиков установок, активных ботов и актуальной версии на сайте;
- без согласия на эту анонимную статистику установка бота невозможна.
AGREEMENT
}

show_install_terms() {
  print_step 2 "Условия установки"
  echo "Устанавливая G-PANEL, вы соглашаетесь на отправку анонимной статистики на ${TELEMETRY_URL_FIXED}."
  echo "Это используется только для честных счётчиков установок, активных ботов и актуальной версии на сайте."
  echo
  echo "1) Продолжить установку"
  echo "2) Прочитать соглашение"
  echo "3) Отменить установку"

  local choice=""
  while true; do
    ask_tty "Ваш выбор (1-3): " choice
    case "$choice" in
      1)
        return 0
        ;;
      2)
        echo
        show_agreement
        echo
        local consent="false"
        ask_yes_no "Согласны с условиями и хотите продолжить установку?" consent
        if [[ "$consent" == "true" ]]; then
          return 0
        fi
        print_warn "Установка отменена пользователем из-за отказа от соглашения"
        if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
          rm -f "$SCRIPT_SOURCE" || true
        fi
        exit 1
        ;;
      3|q|quit|exit)
        print_info "Установка отменена"
        if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
          rm -f "$SCRIPT_SOURCE" || true
        fi
        exit 0
        ;;
      *)
        echo "Введите число от 1 до 3."
        ;;
    esac
  done
}

save_protected_files() {
  local backup_dir="$1"
  mkdir -p "$backup_dir"
  local file=""
  for file in "${PROTECTED_FILES[@]}"; do
    [[ -f "${INSTALL_DIR}/${file}" ]] && cp -a "${INSTALL_DIR}/${file}" "${backup_dir}/"
  done
  local dir=""
  for dir in "${PROTECTED_DIRS[@]}"; do
    if [[ -d "${INSTALL_DIR}/${dir}" ]]; then
      mkdir -p "${backup_dir}/${dir}"
      rsync -a "${INSTALL_DIR}/${dir}/" "${backup_dir}/${dir}/" >/dev/null 2>&1 || true
    fi
  done
}

restore_protected_files() {
  local backup_dir="$1"
  [[ -d "$backup_dir" ]] || return 0
  local file=""
  for file in "${PROTECTED_FILES[@]}"; do
    [[ -f "${backup_dir}/${file}" ]] && cp -a "${backup_dir}/${file}" "${INSTALL_DIR}/"
  done
  local dir=""
  for dir in "${PROTECTED_DIRS[@]}"; do
    if [[ -d "${backup_dir}/${dir}" ]]; then
      mkdir -p "${INSTALL_DIR}/${dir}"
      rsync -a "${backup_dir}/${dir}/" "${INSTALL_DIR}/${dir}/" >/dev/null 2>&1 || true
    fi
  done
}

clone_repo() {
  local target_dir="$1"
  local tmp_tar=""
  local url=""
  local candidates=("$REPO_GIT_URL" "$REPO_URL")

  for url in "${candidates[@]}"; do
    print_info "Проверяю репозиторий: ${url}"
    if git ls-remote "$url" HEAD >> "$LOG_FILE" 2>> "$ERROR_LOG"; then
      print_info "Клонирую ${url}"
      if git clone --depth 1 --branch main "$url" "$target_dir" >> "$LOG_FILE" 2>> "$ERROR_LOG"; then
        print_ok "Код успешно получен из GitHub"
        return 0
      fi
      print_warn "git clone не удался для ${url}, пробую следующий способ"
    else
      print_warn "git ls-remote не смог проверить ${url}"
    fi
  done

  print_warn "Пробую резервный способ через GitHub tarball"
  tmp_tar="$(mktemp "${HOME}/server-bot-src.XXXXXX.tar.gz")"
  if curl -fsSL --retry 3 "$REPO_TARBALL_URL" -o "$tmp_tar" >> "$LOG_FILE" 2>> "$ERROR_LOG"; then
    mkdir -p "$target_dir"
    tar -xzf "$tmp_tar" -C "$target_dir" --strip-components=1 >> "$LOG_FILE" 2>> "$ERROR_LOG" || {
      rm -f "$tmp_tar"
      return 1
    }
    rm -f "$tmp_tar"
    (
      cd "$target_dir"
      git init >> "$LOG_FILE" 2>> "$ERROR_LOG" || true
      git remote add origin "$REPO_GIT_URL" >> "$LOG_FILE" 2>> "$ERROR_LOG" || true
      git fetch --depth 1 origin main >> "$LOG_FILE" 2>> "$ERROR_LOG" || true
      git reset --hard FETCH_HEAD >> "$LOG_FILE" 2>> "$ERROR_LOG" || true
    )
    print_ok "Код успешно получен через GitHub tarball"
    return 0
  fi

  rm -f "$tmp_tar" || true
  return 1
}

send_uninstall_telemetry() {
  local py=""
  py="${INSTALL_DIR}/venv/bin/python"
  if [[ -x "$py" && -f "${INSTALL_DIR}/telemetry_ctl.py" ]]; then
    TELEMETRY_URL="${TELEMETRY_URL_FIXED}" "$py" "${INSTALL_DIR}/telemetry_ctl.py" uninstall >/dev/null 2>&1 || true
  fi
}

choose_mode() {
  print_step 3 "Выбор режима установки"
  if [[ ! -d "$INSTALL_DIR" ]]; then
    MODE="install"
    return 0
  fi

  echo "Найдена существующая установка: ${INSTALL_DIR}"
  echo
  echo "1) Обновить код с сохранением данных"
  echo "2) Полная переустановка"
  echo "3) Починить окружение и сервис"
  echo "4) Полностью удалить бота"
  echo "5) Выход"
  echo

  local choice=""
  while true; do
    ask_tty "Ваш выбор (1-5): " choice
    case "$choice" in
      1) MODE="update_keep"; return 0 ;;
      2) MODE="reinstall_clean"; return 0 ;;
      3) MODE="repair_only"; return 0 ;;
      4) MODE="uninstall"; return 0 ;;
      5|q|quit|exit) MODE="exit"; return 0 ;;
      *) echo "Введите число от 1 до 5." ;;
    esac
  done
}

remove_installation() {
  print_step 4 "Полное удаление бота"
  send_uninstall_telemetry
  sudo systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  sudo systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
  sudo rm -f "$SERVICE_FILE" "$SUDOERS_FILE" "$MANAGER_PATH" "$ROOT_HELPER_PATH"
  sudo systemctl daemon-reload
  rm -rf "$INSTALL_DIR"
  print_ok "Бот полностью удалён"
}

sync_code() {
  local mode="$1"
  print_step 4 "Получаю код проекта"

  case "$mode" in
    update_keep)
      TMP_BACKUP_DIR="$(mktemp -d "${HOME}/.server-bot-backup.XXXXXX")"
      save_protected_files "$TMP_BACKUP_DIR"
      rm -rf "$INSTALL_DIR"
      ;;
    reinstall_clean)
      local keep_data="false"
      ask_yes_no "Сохранить текущие данные (.env, БД, OAuth, backups) перед переустановкой?" keep_data
      if [[ "$keep_data" == "true" ]]; then
        TMP_BACKUP_DIR="$(mktemp -d "${HOME}/.server-bot-backup.XXXXXX")"
        save_protected_files "$TMP_BACKUP_DIR"
      fi
      rm -rf "$INSTALL_DIR"
      ;;
    repair_only)
      print_info "Режим починки: оставляю текущий код проекта"
      return 0
      ;;
  esac

  if [[ -d "$INSTALL_DIR" ]]; then
    die "Каталог ${INSTALL_DIR} уже существует и не был очищен. Удалите его вручную или выберите другой режим."
  fi

  clone_repo "$INSTALL_DIR" || \
    die "Не удалось получить проект из GitHub. Проверьте доступ к ${REPO_URL} и повторите установку"

  if [[ -n "$TMP_BACKUP_DIR" ]]; then
    restore_protected_files "$TMP_BACKUP_DIR"
  fi
}

setup_python() {
  print_step 5 "Настраиваю Python и зависимости"
  print_info "Создаю виртуальное окружение"
  python3 -m venv "$VENV_DIR" || die "Не удалось создать виртуальное окружение"

  source "$VENV_DIR/bin/activate"
  print_info "Обновляю pip"
  pip install --upgrade pip >> "$LOG_FILE" 2>> "$ERROR_LOG" || die "Не удалось обновить pip"
  print_info "Устанавливаю Python-зависимости"
  pip install -r "$INSTALL_DIR/requirements.txt" >> "$LOG_FILE" 2>> "$ERROR_LOG" || \
    die "Не удалось установить Python-зависимости"
  print_ok "Python-зависимости установлены"
}

setup_env() {
  print_step 6 "Настраиваю .env"

  local token=""
  local admin_id=""
  local server_name="MyVPS"

  echo "Сейчас будут заполнены основные настройки бота."
  echo "TELEMETRY_URL будет жёстко установлен на ${TELEMETRY_URL_FIXED}."
  echo

  if [[ -f "$INSTALL_DIR/.env" ]]; then
    token="$(grep -E '^BOT_TOKEN=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
    admin_id="$(grep -E '^ADMIN_ID=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
    server_name="$(grep -E '^SERVER_NAME=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || echo MyVPS)"
  fi

  while [[ -z "$token" ]]; do
    ask_tty "Введите BOT_TOKEN от BotFather: " token
  done
  while [[ -z "$admin_id" ]]; do
    ask_tty "Введите ADMIN_ID администратора Telegram: " admin_id
  done
  local input_name=""
  ask_tty "Введите SERVER_NAME [${server_name}]: " input_name
  [[ -n "$input_name" ]] && server_name="$input_name"

  cat > "$INSTALL_DIR/.env" <<ENVEOF
BOT_TOKEN=${token}
ADMIN_ID=${admin_id}
SERVER_NAME=${server_name}
TELEMETRY_URL=${TELEMETRY_URL_FIXED}
TELEMETRY_ENABLED=true
TELEMETRY_TIMEOUT=10
ENVEOF
  chmod 600 "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/oauth-credentials.json" 2>/dev/null || true
  chmod 600 "$INSTALL_DIR/token.pickle" 2>/dev/null || true
  print_ok ".env заполнен"

  if [[ ! -f "$INSTALL_DIR/config.py" && -f "$INSTALL_DIR/config.example.py" ]]; then
    cp "$INSTALL_DIR/config.example.py" "$INSTALL_DIR/config.py"
    print_ok "Создан config.py из config.example.py"
  fi
}

setup_logs_and_rights() {
  print_step 7 "Настраиваю логи и права"
  sudo mkdir -p /var/log/server-bot
  sudo chown "$(id -un):$(id -gn)" /var/log/server-bot
  print_ok "Каталог логов готов"
}

create_root_helper() {
  sudo tee "$ROOT_HELPER_PATH" >/dev/null <<'ROOTHELPEOF'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ACTION="${1:-}"
shift || true
SERVICE_NAME="server-bot.service"

case "$ACTION" in
  apt-update)
    exec /usr/bin/apt-get update
    ;;
  apt-upgrade)
    exec /usr/bin/apt-get upgrade -y
    ;;
  apt-autoremove)
    exec /usr/bin/apt-get autoremove --purge -y
    ;;
  apt-autoclean)
    exec /usr/bin/apt-get autoclean -y
    ;;
  restart-bot)
    exec /usr/bin/systemctl restart "$SERVICE_NAME"
    ;;
  grant-docker-access)
    if ! getent group docker >/dev/null 2>&1; then
      echo "docker group not found" >&2
      exit 1
    fi
    /usr/sbin/usermod -aG docker "__SERVICE_USER__"
    exec /usr/bin/systemctl restart "$SERVICE_NAME"
    ;;
  reboot-host)
    if command -v reboot >/dev/null 2>&1; then
      exec "$(command -v reboot)"
    fi
    echo "reboot command not found" >&2
    exit 1
    ;;
  status|restart|stop|start)
    target="${1:-$SERVICE_NAME}"
    exec /usr/bin/systemctl "$ACTION" "$target"
    ;;
  logs)
    if [[ "$#" -eq 0 ]]; then
      exec /usr/bin/journalctl -u "$SERVICE_NAME" -n 100 --no-pager
    fi
    exec /usr/bin/journalctl "$@"
    ;;
  *)
    echo "Unsupported action: ${ACTION}" >&2
    exit 64
    ;;
esac
ROOTHELPEOF
  sudo chown root:root "$ROOT_HELPER_PATH"
  sudo chmod 755 "$ROOT_HELPER_PATH"
}

setup_sudoers() {
  sudo tee "$SUDOERS_FILE" >/dev/null <<SUDOE
$(id -un) ALL=(root) NOPASSWD: ${ROOT_HELPER_PATH}
SUDOE
  sudo chmod 440 "$SUDOERS_FILE"
}

install_manager() {
  print_step 8 "Устанавливаю консольное меню bot"

  cat > "$INSTALL_DIR/bot-manager.sh" <<'MANAGEREOF'
#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="__INSTALL_DIR__"
SERVICE="server-bot"
TELEMETRY_URL="__TELEMETRY_URL__"
ROOT_HELPER="__ROOT_HELPER__"

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
MANAGEREOF

  sed -i "s|__INSTALL_DIR__|${INSTALL_DIR}|g" "$INSTALL_DIR/bot-manager.sh"
  sed -i "s|__TELEMETRY_URL__|${TELEMETRY_URL_FIXED}|g" "$INSTALL_DIR/bot-manager.sh"
  sed -i "s|__ROOT_HELPER__|${ROOT_HELPER_PATH}|g" "$INSTALL_DIR/bot-manager.sh"
  sudo sed -i "s|__SERVICE_USER__|$(id -un)|g" "$ROOT_HELPER_PATH"

  chmod 755 "$INSTALL_DIR/bot-manager.sh"
  sudo install -m 755 "$INSTALL_DIR/bot-manager.sh" "$MANAGER_PATH"
  print_ok "Команда 'bot' установлена"
}

setup_service() {
  print_step 9 "Создаю systemd сервис"
  create_root_helper
  setup_sudoers
  sudo tee "$SERVICE_FILE" >/dev/null <<SERVEOF
[Unit]
Description=Server Management Bot by GigaBlyate
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
Group=$(id -gn)
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=TELEMETRY_URL=${TELEMETRY_URL_FIXED}
Environment=BOT_ROOT_HELPER=${ROOT_HELPER_PATH}
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/bot.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
UMask=0077
PrivateTmp=true
ProtectHome=read-only
ReadWritePaths=${INSTALL_DIR} /var/log/server-bot

[Install]
WantedBy=multi-user.target
SERVEOF
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
  print_ok "systemd сервис создан"
}

integrity_check() {
  print_step 10 "Проверяю целостность файлов"
  source "$VENV_DIR/bin/activate"
  python -m compileall "$INSTALL_DIR" >/dev/null || die "Проверка Python-файлов завершилась ошибкой"
  print_ok "Проверка Python-файлов прошла успешно"
}

start_service() {
  print_step 11 "Запускаю бота"
  sudo systemctl restart "$SERVICE_NAME" || die "Не удалось запустить systemd сервис"
  sleep 2
  print_ok "Бот запущен"
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
}

main() {
  : > "$LOG_FILE"
  : > "$ERROR_LOG"

  require_non_root
  require_sudo
  ensure_packages
  show_install_terms
  choose_mode

  case "$MODE" in
    uninstall)
      remove_installation
      exit 0
      ;;
    exit)
      print_info "Установка отменена"
      exit 0
      ;;
    install|update_keep|reinstall_clean|repair_only)
      sync_code "$MODE"
      setup_python
      setup_env
      setup_logs_and_rights
      install_manager
      setup_service
      integrity_check
      start_service
      ;;
    *)
      die "Неизвестный режим установки: ${MODE}"
      ;;
  esac

  print_ok "Установка завершена. Откройте Telegram и используйте /start"
  print_info "Для локального управления используйте команду: bot"
}

main "$@"
