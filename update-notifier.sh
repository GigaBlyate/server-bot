#!/bin/bash

# Получаем путь к папке, где лежит скрипт
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Конфигурация
BOT_TOKEN=$(grep TOKEN "$SCRIPT_DIR/config.py" | cut -d '"' -f2)
CHAT_ID=$(grep ADMIN_CHAT_ID "$SCRIPT_DIR/config.py" | cut -d '"' -f2)
SERVER_NAME=$(grep SERVER_NAME "$SCRIPT_DIR/config.py" | cut -d '"' -f2)

LOG_FILE="/var/log/unattended-upgrades/unattended-upgrades.log"
NOTIFIER_LOG="$SCRIPT_DIR/update-notifier.log"

# Функция логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$NOTIFIER_LOG"
}

# Функция отправки в Telegram
send_telegram() {
    log "Отправка сообщения в Telegram"
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$1" \
        -d "parse_mode=HTML" > /dev/null
    log "Сообщение отправлено"
}

# Начало работы
log "=== Запуск проверки обновлений ==="
log "LOG_FILE: $LOG_FILE"

# Проверяем существование файла
if [ ! -f "$LOG_FILE" ]; then
    log "ОШИБКА: Файл лога не найден!"
    exit 1
fi

# Проверяем, что файл читается
if [ ! -r "$LOG_FILE" ]; then
    log "ОШИБКА: Нет прав на чтение файла лога"
    exit 1
fi

# Текущая дата для сравнения (формат: YYYY-MM-DD)
TODAY=$(date '+%Y-%m-%d')
log "Текущая дата: $TODAY"

# Извлекаем записи лога за сегодня (строки, начинающиеся с TODAY)
# Используем sudo для чтения, если необходимо
TODAY_LOG=$(sudo awk -v today="$TODAY" '$0 ~ "^" today {print}' "$LOG_FILE" 2>/dev/null)

if [ -z "$TODAY_LOG" ]; then
    log "Записей за сегодня не найдено. Система актуальна."
    MESSAGE="🖥️ <b>$SERVER_NAME</b> - Отчёт об обновлениях
━━━━━━━━━━━━━━━━━━━━━
📅 Дата: $(date '+%Y-%m-%d %H:%M:%S')

✅ Система актуальна. Обновлений не найдено."
    send_telegram "$MESSAGE"
    exit 0
fi

# Проверяем, были ли установлены обновления (наличие строки "All upgrades installed")
if echo "$TODAY_LOG" | grep -q "All upgrades installed"; then
    log "Найдены установленные обновления за сегодня."

    # Собираем список обновлённых пакетов
    # Сначала ищем строку "Packages that will be upgraded:" и берём следующую строку с пакетами
    UPGRADED=$(echo "$TODAY_LOG" | grep -A1 "Packages that will be upgraded:" | tail -1 | sed 's/^[[:space:]]*//' | cut -c1-150)
    # Если не нашли, возможно пакеты перечислены в той же строке после двоеточия
    if [ -z "$UPGRADED" ] || [ "$UPGRADED" = "Packages that will be upgraded:" ]; then
        UPGRADED=$(echo "$TODAY_LOG" | grep "Packages that will be upgraded:" | cut -d':' -f2- | sed 's/^[[:space:]]*//' | cut -c1-150)
    fi

    # Собираем список автоматически удалённых пакетов
    REMOVED=$(echo "$TODAY_LOG" | grep -A1 "Packages that were successfully auto-removed:" | tail -1 | sed 's/^[[:space:]]*//' | cut -c1-150)
    if [ -z "$REMOVED" ] || [ "$REMOVED" = "Packages that were successfully auto-removed:" ]; then
        REMOVED=$(echo "$TODAY_LOG" | grep "Packages that were successfully auto-removed:" | cut -d':' -f2- | sed 's/^[[:space:]]*//' | cut -c1-150)
    fi

    # Формируем сообщение
    MESSAGE="🖥️ <b>$SERVER_NAME</b> - Отчёт об обновлениях
━━━━━━━━━━━━━━━━━━━━━
📅 Дата: $(date '+%Y-%m-%d %H:%M:%S')

✅ Обновления успешно установлены."

    if [ -n "$UPGRADED" ]; then
        MESSAGE="$MESSAGE\n\n📦 <b>Обновлено:</b> $UPGRADED"
    fi

    if [ -n "$REMOVED" ]; then
        MESSAGE="$MESSAGE\n\n🗑️ <b>Удалено:</b> $REMOVED"
    fi

    # Проверяем, требуется ли перезагрузка
    if echo "$TODAY_LOG" | grep -q "reboot-required"; then
        MESSAGE="$MESSAGE\n\n⚠️ <b>Требуется перезагрузка!</b>"
    fi

    send_telegram "$MESSAGE"
    log "Уведомление отправлено"
else
    # Если записи за сегодня есть, но обновления не устанавливались
    log "За сегодня обновлений не устанавливалось."
    MESSAGE="🖥️ <b>$SERVER_NAME</b> - Отчёт об обновлениях
━━━━━━━━━━━━━━━━━━━━━
📅 Дата: $(date '+%Y-%m-%d %H:%M:%S')

✅ Система актуальна. Обновлений не найдено."
    send_telegram "$MESSAGE"
fi

log "=== Проверка завершена ==="
