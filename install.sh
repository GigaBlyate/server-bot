#!/bin/bash

# =============================================
# 🚀 БЫСТРЫЙ УСТАНОВЩИК БОТА
# =============================================

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Конфигурация
REPO="GigaBlyate/server-bot"
INSTALL_DIR="$HOME/server-bot"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="$HOME/install-bot.log"

# Функция прогресс-бара
progress_bar() {
    local duration=${1:-2}
    local width=50
    local bar_char="█"
    local empty_char="░"
    
    echo -n " "
    for ((i=0; i<=width; i++)); do
        local percent=$((i * 100 / width))
        local bars=$i
        local empty=$((width - i))
        printf "\r${CYAN}[${GREEN}"
        printf "%0.s${bar_char}" $(seq 1 $bars)
        printf "${NC}${CYAN}%0.s${empty_char}" $(seq 1 $empty)
        printf "${CYAN}] ${YELLOW}%3d%%${NC}" $percent
        sleep $(bc <<< "scale=2; $duration/$width")
    done
    echo
}

# Новый логотип (более простой)
show_logo() {
    clear
    echo -e "${PURPLE}"
    echo "╔════════════════════════════════════════════════════╗"
    echo "║                                                    ║"
    echo "║    ██████  ██████  ████████     ██████  ██████     ║"
    echo "║   ██░░░░██░░██░░██░░██░░██    ██░░░░██░░██░░██    ║"
    echo "║  ██    ░░  ██  ░░  ██  ░█   ██    ░░  ██  ░█    ║"
    echo "║  ██        ██      █████    ██        █████      ║"
    echo "║  ██    ██  ██      ██  ██   ██    ██  ██  ██     ║"
    echo "║  ░░██████  ██████  ████████  ░░██████  ████████   ║"
    echo "║    ░░░░░░  ░░░░░░  ░░░░░░░░    ░░░░░░  ░░░░░░░░   ║"
    echo "║                                                    ║"
    echo "║              🤖 SERVER BOT v2.1.0 🤖              ║"
    echo "║                                                    ║"
    echo "║                by ${CYAN}GigaBlyate${PURPLE}                    ║"
    echo "║     https://github.com/GigaBlyate/server-bot      ║"
    echo "╚════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Функция проверки и установки пакетов
check_and_install() {
    echo -e "\n${BLUE}📦 Проверка: $1${NC}"
    if ! command -v $2 &> /dev/null; then
        echo -e "${YELLOW}⚠️  Устанавливаю $1...${NC}"
        sudo apt update >> "$LOG_FILE" 2>&1
        sudo apt install -y $3 >> "$LOG_FILE" 2>&1
        progress_bar 1
        echo -e "${GREEN}✅ $1 установлен${NC}"
    else
        echo -e "${GREEN}✅ $1 уже установлен${NC}"
        progress_bar 0.5
    fi
}

# Функция установки Python библиотек
install_python_deps() {
    echo -e "\n${BLUE}📚 Установка Python библиотек...${NC}"
    source "$VENV_DIR/bin/activate"
    
    # Основные библиотеки
    local packages=(
        "python-telegram-bot==20.7"
        "psutil==5.9.5"
        "aiohttp==3.9.1"
        "cryptography==41.0.7"
        "sqlite3"
    )
    
    local total=${#packages[@]}
    local current=0
    
    for pkg in "${packages[@]}"; do
        current=$((current + 1))
        echo -ne "\r${CYAN}⏳ Установка [$current/$total]: $pkg${NC}"
        pip install -q "$pkg" >> "$LOG_FILE" 2>&1
        sleep 0.3
    done
    echo -e "\r${GREEN}✅ Все библиотеки установлены!${NC}                       "
}

# =============================================
# ГЛАВНЫЙ ПРОЦЕСС
# =============================================

show_logo

echo -e "\n${WHITE}Добро пожаловать! Скрипт установит всё необходимое.${NC}"
read -p "Продолжить? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Установка отменена${NC}"
    exit 0
fi

# 1. СИСТЕМНЫЕ ЗАВИСИМОСТИ
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  🔧 ПРОВЕРКА СИСТЕМЫ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_and_install "Git" "git" "git"
check_and_install "Python3" "python3" "python3 python3-pip python3-venv"
check_and_install "SQLite3" "sqlite3" "sqlite3"

echo -e "\n${GREEN}✅ Все системные требования выполнены!${NC}"

# 2. КЛОНИРОВАНИЕ
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  📥 ЗАГРУЗКА БОТА${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}⚠️  Папка $INSTALL_DIR уже существует${NC}"
    read -p "Удалить и переустановить? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        echo -e "${YELLOW}Пропускаю клонирование${NC}"
        SKIP_CLONE=1
    fi
fi

if [ ! -d "$INSTALL_DIR" ] && [ "$SKIP_CLONE" != 1 ]; then
    echo -e "Клонирование репозитория..."
    git clone "https://github.com/$REPO.git" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1
    progress_bar 2
    echo -e "${GREEN}✅ Репозиторий загружен${NC}"
fi

cd "$INSTALL_DIR"

# 3. ВИРТУАЛЬНОЕ ОКРУЖЕНИЕ
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  🐍 НАСТРОЙКА PYTHON${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ ! -d "$VENV_DIR" ]; then
    echo -e "Создание виртуального окружения..."
    python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1
    progress_bar 1
    echo -e "${GREEN}✅ Виртуальное окружение создано${NC}"
else
    echo -e "${GREEN}✅ Виртуальное окружение уже есть${NC}"
fi

# 4. УСТАНОВКА БИБЛИОТЕК
install_python_deps

# 5. БАЗА ДАННЫХ
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  🗄️  НАСТРОЙКА БАЗЫ ДАННЫХ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ ! -f "vps_data.db" ]; then
    sqlite3 vps_data.db << EOF
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES 
    ('cpu_threshold', '30'),
    ('ram_threshold', '85'),
    ('disk_threshold', '85'),
    ('monitor_interval', '30'),
    ('enable_daily_report', 'false'),
    ('enable_fail2ban_alerts', 'false'),
    ('compact_mode', 'false');
EOF
    echo -e "${GREEN}✅ База данных создана${NC}"
else
    echo -e "${GREEN}✅ База данных уже существует${NC}"
fi

# 6. SYSTEMD СЕРВИС
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  ⚙️  НАСТРОЙКА АВТОЗАПУСКА${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

cat > /tmp/server-bot.service << EOF
[Unit]
Description=Server Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/server-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable server-bot >> "$LOG_FILE" 2>&1
echo -e "${GREEN}✅ Сервис создан и добавлен в автозагрузку${NC}"

# 7. ЗАПУСК
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  🚀 ЗАПУСК БОТА${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

sudo systemctl start server-bot
sleep 3

if sudo systemctl is-active --quiet server-bot; then
    echo -e "${GREEN}✅ Бот успешно запущен!${NC}"
else
    echo -e "${RED}❌ Ошибка запуска. Проверьте логи:${NC}"
    echo "sudo journalctl -u server-bot -n 20 --no-pager"
fi

# 8. МЕНЮ УПРАВЛЕНИЯ
cat > "$HOME/bot" << EOF
#!/bin/bash
echo -e "${PURPLE}"
echo "╔════════════════════════════════════════╗"
echo "║       🤖 УПРАВЛЕНИЕ БОТОМ 🤖         ║"
echo "╠════════════════════════════════════════╣"
echo "║ 1. Статус                             ║"
echo "║ 2. Логи                                ║"
echo "║ 3. Перезапустить                       ║"
echo "║ 4. Остановить                          ║"
echo "║ 5. Запустить                           ║"
echo "║ 6. Выйти                               ║"
echo "╚════════════════════════════════════════╝${NC}"
read -p "Выберите действие: " cmd
case \$cmd in
    1) sudo systemctl status server-bot ;;
    2) sudo journalctl -u server-bot -f ;;
    3) sudo systemctl restart server-bot ;;
    4) sudo systemctl stop server-bot ;;
    5) sudo systemctl start server-bot ;;
    6) exit 0 ;;
esac
EOF

chmod +x "$HOME/bot"

# 9. ФИНАЛ
echo -e "\n${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🎉 УСТАНОВКА ЗАВЕРШЕНА!                           ║${NC}"
echo -e "${GREEN}║                                                    ║${NC}"
echo -e "${GREEN}║  Команды для управления:                           ║${NC}"
echo -e "${GREEN}║  ${CYAN}./bot${GREEN} - простое меню                         ║${NC}"
echo -e "${GREEN}║  ${CYAN}sudo systemctl status server-bot${GREEN} - статус  ║${NC}"
echo -e "${GREEN}║  ${CYAN}sudo journalctl -u server-bot -f${GREEN} - логи   ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════╝${NC}"
