#!/bin/bash

# =============================================
# 🚀 УСТАНОВЩИК TELEGRAM БОТА GigaBlyate/server-bot
# =============================================

set -e  # Прерывать при ошибках

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Конфигурация
REPO="GigaBlyate/server-bot"
INSTALL_DIR="$HOME/server-bot"
VENV_DIR="$INSTALL_DIR/venv"
LOG_FILE="$HOME/install-bot.log"

# Функция для красивого вывода
print_step() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  🔹 $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ️ $1${NC}"
}

# Очистка экрана
clear

# Приветствие
echo -e "${PURPLE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║   ██████  ██ ▄█▀ ▄▄▄          ██████ ██▓▓█████▄▄▄█████▓     ║"
echo "║ ▒██    ▒  ██▄█▒ ▒████▄      ▒██    ▒ ▓██▒▓█   ▀▓  ██▒ ▓▒    ║"
echo "║ ░ ▓██▄   ▓███▄░ ▒██  ▀█▄    ░ ▓██▄   ▒██▒▒███  ▒ ▓██░ ▒░    ║"
echo "║   ▒   ██▒▓██ █▄ ░██▄▄▄▄██     ▒   ██▒░██░▒▓█  ▄░ ▓██▓ ░     ║"
echo "║ ▒██████▒▒▒██▒ █▄ ▓█   ▓██▒▒██████▒▒░██░░▒████▒ ▒██▒ ░     ║"
echo "║ ▒ ▒▓▒ ▒ ░▒ ▒▒ ▓▒ ▒▒   ▓▒█░▒ ▒▓▒ ▒ ░░▓  ░░ ▒░ ░ ▒ ░░       ║"
echo "║ ░ ░▒  ░ ░░ ░▒ ▒░  ░   ▒▒ ░░ ░▒  ░ ░ ▒ ░ ░ ░  ░   ░        ║"
echo "║ ░  ░  ░  ░ ░░ ░   ░   ▒   ░  ░  ░   ▒ ░   ░    ░          ║"
echo "║       ░  ░  ░         ░  ░      ░   ░     ░  ░             ║"
echo "║                                                              ║"
echo "║              🤖 SERVER MANAGEMENT BOT v2.1.0 🤖            ║"
echo "║                                                              ║"
echo "║                   by ${CYAN}GigaBlyate${PURPLE}                         ║"
echo "║              https://github.com/GigaBlyate/server-bot       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "\n${WHITE}Добро пожаловать в установщик Telegram бота для управления сервером!${NC}"
echo -e "${YELLOW}Скрипт автоматически установит и настроит всё необходимое.${NC}\n"

# Проверка, что скрипт не запущен от root
if [[ $EUID -eq 0 ]]; then
   print_error "Этот скрипт не должен запускаться от root!"
   echo "Запустите его от обычного пользователя: ./install.sh"
   exit 1
fi

echo -e "\n${WHITE}Добро пожаловать в установщик Telegram бота для управления сервером!${NC}"
echo -e "${YELLOW}Скрипт автоматически установит и настроит всё необходимое.${NC}\n"

# Запрос подтверждения
read -p "Продолжить установку? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_info "Установка отменена"
    exit 0
fi

# =============================================
# 1. ПРОВЕРКА ЗАВИСИМОСТЕЙ
# =============================================
print_step "ПРОВЕРКА ЗАВИСИМОСТЕЙ"

# Проверка Git
if ! command -v git &> /dev/null; then
    print_info "Git не найден. Устанавливаю..."
    sudo apt update >> "$LOG_FILE" 2>&1
    sudo apt install git -y >> "$LOG_FILE" 2>&1
    print_success "Git установлен"
else
    print_success "Git уже установлен"
fi

# Проверка Python3
if ! command -v python3 &> /dev/null; then
    print_info "Python3 не найден. Устанавливаю..."
    sudo apt update >> "$LOG_FILE" 2>&1
    sudo apt install python3 python3-pip python3-venv -y >> "$LOG_FILE" 2>&1
    print_success "Python3 установлен"
else
    print_success "Python3 уже установлен"
fi

# Проверка pip
if ! command -v pip3 &> /dev/null; then
    print_info "pip3 не найден. Устанавливаю..."
    sudo apt install python3-pip -y >> "$LOG_FILE" 2>&1
    print_success "pip3 установлен"
else
    print_success "pip3 уже установлен"
fi

# Установка необходимых системных пакетов
print_info "Устанавливаю системные пакеты..."
sudo apt install -y python3-venv python3-dev build-essential wget curl >> "$LOG_FILE" 2>&1
print_success "Системные пакеты установлены"

# =============================================
# 2. КЛОНИРОВАНИЕ РЕПОЗИТОРИЯ
# =============================================
print_step "КЛОНИРОВАНИЕ РЕПОЗИТОРИЯ"

if [ -d "$INSTALL_DIR" ]; then
    print_info "Папка $INSTALL_DIR уже существует"
    echo ""
    echo "Выберите действие:"
    echo "  1) Переустановить (удалить всё и установить заново)"
    echo "  2) Обновить (сохранить config.py и базу данных)"
    echo "  3) Пропустить"
    echo ""
    read -p "Ваш выбор (1/2/3): " upgrade_choice
    
    case $upgrade_choice in
        1)
            print_info "Полная переустановка. Удаляю старую версию..."
            rm -rf "$INSTALL_DIR"
            ;;
        2)
            print_info "Обновление. Сохраняю config.py и vps_data.db..."
            if [ -f "$INSTALL_DIR/config.py" ]; then
                cp "$INSTALL_DIR/config.py" /tmp/config.py.backup
            fi
            if [ -f "$INSTALL_DIR/vps_data.db" ]; then
                cp "$INSTALL_DIR/vps_data.db" /tmp/vps_data.db.backup
            fi
            rm -rf "$INSTALL_DIR"
            ;;
        3)
            print_info "Пропускаю клонирование"
            SKIP_CLONE=1
            ;;
    esac
fi

if [ ! -d "$INSTALL_DIR" ] && [ "$SKIP_CLONE" != 1 ]; then
    print_info "Клонирую репозиторий $REPO..."
    git clone "https://github.com/$REPO.git" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1
    print_success "Репозиторий склонирован"
    
    # Восстанавливаем бэкапы если нужно
    if [ "$upgrade_choice" = "2" ]; then
        if [ -f "/tmp/config.py.backup" ]; then
            mv /tmp/config.py.backup "$INSTALL_DIR/config.py"
            print_success "config.py восстановлен"
        fi
        if [ -f "/tmp/vps_data.db.backup" ]; then
            mv /tmp/vps_data.db.backup "$INSTALL_DIR/vps_data.db"
            print_success "База данных восстановлена"
        fi
    fi
fi

cd "$INSTALL_DIR"

# =============================================
# 3. НАСТРОЙКА ВИРТУАЛЬНОГО ОКРУЖЕНИЯ
# =============================================
print_step "НАСТРОЙКА ВИРТУАЛЬНОГО ОКРУЖЕНИЯ"

if [ ! -d "$VENV_DIR" ]; then
    print_info "Создаю виртуальное окружение..."
    python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1
    print_success "Виртуальное окружение создано"
else
    print_success "Виртуальное окружение уже существует"
fi

# Активация и установка зависимостей
print_info "Активирую виртуальное окружение..."
source "$VENV_DIR/bin/activate"

if [ -f "requirements.txt" ]; then
    print_info "Устанавливаю зависимости..."
    pip install --upgrade pip >> "$LOG_FILE" 2>&1
    pip install -r requirements.txt >> "$LOG_FILE" 2>&1
    print_success "Зависимости установлены"
else
    print_error "Файл requirements.txt не найден!"
    exit 1
fi

# =============================================
# 4. НАСТРОЙКА КОНФИГУРАЦИИ
# =============================================
print_step "НАСТРОЙКА КОНФИГУРАЦИИ"

if [ ! -f "config.py" ]; then
    if [ -f "config.example.py" ]; then
        cp config.example.py config.py
        print_info "Создан файл config.py из примера"
        
        # Автоматически получаем имя пользователя
        USER_NAME=$(whoami)
        
        echo ""
        echo -e "${YELLOW}⚠️  ТРЕБУЕТСЯ НАСТРОЙКА!${NC}"
        echo -e "${WHITE}Сейчас откроется редактор для файла config.py${NC}"
        echo "Пожалуйста, укажите следующие данные:"
        echo "  1. TOKEN - получите у \033[4;34m@BotFather\033[0m в Telegram: \033[4;34mhttps://t.me/botfather\033[0m"
        echo "  2. ADMIN_CHAT_ID - ваш Telegram ID (узнайте у \033[4;34m@userinfobot\033[0m:\033[4;34mhttps://t.me/userinfobot\033[0m)"
        echo "  3. SERVER_NAME - название вашего сервера (например, MyVPS)"
        echo ""
        read -p "Нажмите Enter, чтобы открыть редактор..."
        
        # Определяем редактор
        if command -v nano &> /dev/null; then
            nano config.py
        elif command -v vim &> /dev/null; then
            vim config.py
        else
            vi config.py
        fi
    else
        print_error "Файл config.example.py не найден!"
        exit 1
    fi
else
    print_success "Файл config.py уже существует"
    read -p "Хотите отредактировать его? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if command -v nano &> /dev/null; then
            nano config.py
        elif command -v vim &> /dev/null; then
            vim config.py
        else
            vi config.py
        fi
    fi
fi

# =============================================
# 5. ПРОВЕРКА ТОКЕНА
# =============================================
print_step "ПРОВЕРКА ТОКЕНА"

TOKEN=$(grep -E '^TOKEN\s*=' config.py | grep -o '"[^"]*"' | head -1 | tr -d '"')
if [ -z "$TOKEN" ] || [ "$TOKEN" = "YOUR_BOT_TOKEN_HERE" ]; then
    print_error "Токен не настроен!"
    echo "Пожалуйста, вставьте правильный токен в config.py"
    if command -v nano &> /dev/null; then
        nano config.py
    else
        vi config.py
    fi
else
    print_success "Токен настроен: ${TOKEN:0:10}..."
fi

# =============================================
# 6. НАСТРОЙКА SYSTEMD СЕРВИСА
# =============================================
print_step "НАСТРОЙКА SYSTEMD СЕРВИСА"

SERVICE_FILE="/etc/systemd/system/server-bot.service"

if [ ! -f "$SERVICE_FILE" ]; then
    print_info "Создаю systemd сервис..."
    
    # Создаем временный файл
    cat > /tmp/server-bot.service << EOF
[Unit]
Description=Server Management Bot by GigaBlyate
After=network.target
Wants=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    sudo mv /tmp/server-bot.service "$SERVICE_FILE"
    sudo systemctl daemon-reload
    sudo systemctl enable server-bot >> "$LOG_FILE" 2>&1
    print_success "Systemd сервис создан и добавлен в автозагрузку"
else
    print_success "Systemd сервис уже существует"
fi

# =============================================
# 7. СОЗДАНИЕ МЕНЮ УПРАВЛЕНИЯ
# =============================================
print_step "СОЗДАНИЕ МЕНЮ УПРАВЛЕНИЯ"

# Создаем скрипт меню
cat > "$HOME/bot-menu.sh" << 'EOF'
#!/bin/bash

# Цвета
GREEN='\033[0;32m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
WHITE='\033[1;37m'
NC='\033[0m'

while true; do
    clear
    echo -e "${PURPLE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║${NC}        ${WHITE}🤖 GigaBlyate SERVER BOT MANAGER 🤖${NC}        ${PURPLE}║${NC}"
    echo -e "${PURPLE}╠════════════════════════════════════════════════════════╣${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}1.${NC} 🔄 Перезапустить бота                      ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}2.${NC} 📊 Статус бота                            ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}3.${NC} ⏹️  Остановить бота                        ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}4.${NC} ▶️  Запустить бота                         ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}5.${NC} 📜 Логи в реальном времени                ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}6.${NC} ⚠️  Только ошибки                          ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}7.${NC} 📋 Показать все команды                    ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}8.${NC} 🔧 Настройки                               ${PURPLE}║${NC}"
    echo -e "${PURPLE}║${NC}  ${GREEN}9.${NC} 🚪 Выйти                                    ${PURPLE}║${NC}"
    echo -e "${PURPLE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
    read -p "Выберите действие (1-9): " choice

    case $choice in
        1)
            echo -e "${YELLOW}🔄 Перезапускаю бота...${NC}"
            sudo systemctl restart server-bot
            sudo systemctl status server-bot
            read -p "Нажмите Enter для продолжения..."
            ;;
        2)
            echo -e "${YELLOW}📊 Статус бота:${NC}"
            sudo systemctl status server-bot
            read -p "Нажмите Enter для продолжения..."
            ;;
        3)
            echo -e "${YELLOW}⏹️  Останавливаю бота...${NC}"
            sudo systemctl stop server-bot
            echo -e "${GREEN}✅ Бот остановлен${NC}"
            read -p "Нажмите Enter для продолжения..."
            ;;
        4)
            echo -e "${YELLOW}▶️  Запускаю бота...${NC}"
            sudo systemctl start server-bot
            echo -e "${GREEN}✅ Бот запущен${NC}"
            read -p "Нажмите Enter для продолжения..."
            ;;
        5)
            echo -e "${YELLOW}📜 Логи в реальном времени (Ctrl+C для выхода):${NC}"
            sudo journalctl -u server-bot -f
            ;;
        6)
            echo -e "${YELLOW}⚠️  Только ошибки (Ctrl+C для выхода):${NC}"
            sudo journalctl -u server-bot -f | grep -i error
            ;;
        7)
            echo -e "${CYAN}"
            echo "╔════════════════════════════════════════════════════════╗"
            echo "║          📋 ДОСТУПНЫЕ КОМАНДЫ ДЛЯ БОТА               ║"
            echo "╠════════════════════════════════════════════════════════╣"
            echo "║ ${GREEN}bot${NC}         - Открыть это меню                      ║"
            echo "║ ${GREEN}bot-reload${NC}  - Перезапуск бота                      ║"
            echo "║ ${GREEN}bot-status${NC}  - Статус бота                          ║"
            echo "║ ${GREEN}bot-stop${NC}    - Остановить бота                      ║"
            echo "║ ${GREEN}bot-start${NC}   - Запустить бота                       ║"
            echo "║ ${GREEN}bot-logs${NC}    - Логи в реальном времени              ║"
            echo "║ ${GREEN}bot-errors${NC}  - Только ошибки                        ║"
            echo "║ ${GREEN}bot-help${NC}    - Показать справку                     ║"
            echo "║ ${GREEN}bot-guide${NC}   - Показать шпаргалку                   ║"
            echo "╚════════════════════════════════════════════════════════╝${NC}"
            echo ""
            read -p "Нажмите Enter для продолжения..."
            ;;
        8)
            echo -e "${CYAN}"
            echo "╔════════════════════════════════════════════════════════╗"
            echo "║              🔧 НАСТРОЙКИ БОТА                        ║"
            echo "╠════════════════════════════════════════════════════════╣"
            echo "║ 1. Редактировать config.py                            ║"
            echo "║ 2. Показать логи установки                            ║"
            echo "║ 3. Обновить бота с GitHub                             ║"
            echo "║ 4. Назад                                              ║"
            echo "╚════════════════════════════════════════════════════════╝${NC}"
            echo ""
            read -p "Выберите действие: " subchoice
            case $subchoice in
                1)
                    cd ~/server-bot
                    if command -v nano &> /dev/null; then
                        nano config.py
                    else
                        vi config.py
                    fi
                    ;;
                2)
                    cat ~/install-bot.log 2>/dev/null || echo "Логов нет"
                    read -p "Нажмите Enter..."
                    ;;
                3)
                    echo -e "${YELLOW}🔄 Обновляю бота с GitHub...${NC}"
                    cd ~/server-bot
                    git pull
                    source venv/bin/activate
                    pip install -r requirements.txt
                    sudo systemctl restart server-bot
                    echo -e "${GREEN}✅ Бот обновлен${NC}"
                    read -p "Нажмите Enter..."
                    ;;
                4)
                    continue
                    ;;
            esac
            ;;
        9)
            echo -e "${GREEN}👋 До свидания!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Неверный выбор. Попробуйте снова.${NC}"
            read -p "Нажмите Enter для продолжения..."
            ;;
    esac
done
EOF

chmod +x "$HOME/bot-menu.sh"

# Добавляем алиасы в .bashrc, если их там еще нет
if ! grep -q "alias bot=" "$HOME/.bashrc"; then
    cat >> "$HOME/.bashrc" << 'EOF'

# ===== УПРАВЛЕНИЕ БОТОМ GigaBlyate/server-bot =====
alias bot='~/bot-menu.sh'
alias bot-reload='sudo systemctl restart server-bot && sudo systemctl status server-bot'
alias bot-status='sudo systemctl status server-bot'
alias bot-stop='sudo systemctl stop server-bot'
alias bot-start='sudo systemctl start server-bot'
alias bot-logs='sudo journalctl -u server-bot -f'
alias bot-errors='sudo journalctl -u server-bot -f | grep -i error'
alias bot-help='echo -e "\n🤖 ДОСТУПНЫЕ КОМАНДЫ:\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nbot        - Открыть меню\nbot-reload - Перезапуск\nbot-status - Статус\nbot-stop   - Останов\nbot-start  - Запуск\nbot-logs   - Логи\nbot-errors - Ошибки\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"'
alias bot-guide='cat ~/bot-commands.txt'
EOF
    print_success "Алиасы добавлены в .bashrc"
else
    print_success "Алиасы уже существуют"
fi

# Создаем шпаргалку
cat > "$HOME/bot-commands.txt" << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║        🤖 GigaBlyate SERVER BOT - ШПАРГАЛКА КОМАНД 🤖          ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  🔧 ОСНОВНЫЕ КОМАНДЫ:                                            ║
║  ─────────────────────────────────────────────────────────────   ║
║  bot        - Открыть меню управления                            ║
║  bot-reload - Перезапуск + статус                                ║
║  bot-status - Статус бота                                        ║
║  bot-stop   - Остановить бота                                    ║
║  bot-start  - Запустить бота                                     ║
║  bot-logs   - Логи в реальном времени                            ║
║  bot-errors - Только ошибки                                      ║
║  bot-help   - Справка по командам                                ║
║  bot-guide  - Эта шпаргалка                                      ║
║                                                                  ║
║  📋 ПОЛЕЗНЫЕ КОМАНДЫ:                                            ║
║  ─────────────────────────────────────────────────────────────   ║
║  cd ~/server-bot           - Перейти в папку бота                ║
║  source venv/bin/activate  - Активировать окружение              ║
║  python bot.py             - Запустить вручную                   ║
║  nano bot.py               - Редактировать код                   ║
║                                                                  ║
║  🔄 ОБНОВЛЕНИЕ БОТА:                                             ║
║  ─────────────────────────────────────────────────────────────   ║
║  cd ~/server-bot                                                 ║
║  git pull                                                        ║
║  source venv/bin/activate                                        ║
║  pip install -r requirements.txt                                 ║
║  sudo systemctl restart server-bot                               ║
║                                                                  ║
║  ⚠️  ЕСЛИ БОТ НЕ РАБОТАЕТ:                                       ║
║  ─────────────────────────────────────────────────────────────   ║
║  sudo systemctl status server-bot                                ║
║  sudo journalctl -u server-bot -n 50 --no-pager                  ║
║  tail -f ~/server-bot/update-notifier.log                        ║
║                                                                  ║
║  📊 МОНИТОРИНГ:                                                  ║
║  ─────────────────────────────────────────────────────────────   ║
║  sudo journalctl -u server-bot -f | grep -i error                ║
║  tail -f /var/log/crash-monitor.log                              ║
║  sudo systemctl status crash-monitor                             ║
║                                                                  ║
║  GitHub: https://github.com/GigaBlyate/server-bot                ║
║  Версия: 2.1.0                                                   ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
EOF

print_success "Меню управления и шпаргалка созданы"

# =============================================
# 8. ЗАПУСК БОТА
# =============================================
print_step "ЗАПУСК БОТА"

print_info "Запускаю бота..."
sudo systemctl start server-bot
sleep 2

if sudo systemctl is-active --quiet server-bot; then
    print_success "Бот успешно запущен!"
else
    print_error "Бот не запустился. Проверьте логи:"
    echo "sudo journalctl -u server-bot -n 20 --no-pager"
fi

# =============================================
# 9. ПРИМЕНЕНИЕ АЛИАСОВ
# =============================================
print_step "ЗАВЕРШЕНИЕ УСТАНОВКИ"

# Применяем алиасы для текущей сессии
source ~/.bashrc 2>/dev/null || true

print_success "УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!"

echo -e "\n${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}  🎉 ВСЁ ГОТОВО! Бот GigaBlyate/server-bot установлен!      ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}                                                              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  ${WHITE}👉 Чтобы открыть меню управления, введите:${NC}          ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}                       ${CYAN}bot${NC}                               ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}                                                              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  ${WHITE}📱 Перейдите в Telegram и отправьте /start${NC}           ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  ${WHITE}   чтобы начать пользоваться ботом${NC}                   ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}                                                              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  ${WHITE}📚 Если забыли команды:${NC}                              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}                       ${CYAN}bot-help${NC}  или  ${CYAN}bot-guide${NC}            ${GREEN}║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
