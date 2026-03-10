#!/bin/bash

# Конфигурация
BOT_TOKEN=$(grep TOKEN /home/gigablyate/server-bot/config.py | cut -d '"' -f2)
CHAT_ID=$(grep ADMIN_CHAT_ID /home/gigablyate/server-bot/config.py | cut -d '"' -f2)
SERVER_NAME=$(grep SERVER_NAME /home/gigablyate/server-bot/config.py | cut -d '"' -f2)
LOG_FILE="/var/log/unattended-upgrades/unattended-upgrades.log"
NOTIFIER_LOG="/home/gigablyate/server-bot/update-notifier.log"

# Функция логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> $NOTIFIER_LOG
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

# Получаем последние 100 строк лога
LATEST_LOGS=$(sudo tail -100 "$LOG_FILE" 2>/dev/null)

if [ $? -ne 0 ]; then
    log "ОШИБКА: Не удалось прочитать файл лога"
    exit 1
fi

log "Файл лога успешно прочитан"

# Ищем установленные обновления (по разным паттернам)
if echo "$LATEST_LOGS" | grep -q "All upgrades installed"; then
    log "Найдены установленные обновления!"
    
    # Получаем дату последнего обновления
    UPDATE_LINE=$(echo "$LATEST_LOGS" | grep "All upgrades installed" | tail -1)
    UPDATE_DATE=$(echo "$UPDATE_LINE" | cut -d',' -f1)
    
    # Получаем список обновленных пакетов
    UPGRADED=$(echo "$LATEST_LOGS" | grep "Packages that will be upgraded" | tail -1 | cut -d':' -f2- | cut -c1-150)
    REMOVED=$(echo "$LATEST_LOGS" | grep "Packages that were successfully auto-removed" | tail -1 | cut -d':' -f2- | cut -c1-150)
    
    # Формируем сообщение
    MESSAGE="🖥️ <b>$SERVER_NAME</b> - Отчёт об обновлениях
━━━━━━━━━━━━━━━━━━━━━
📅 Дата: $UPDATE_DATE

✅ Обновления успешно установлены."

    if [ ! -z "$UPGRADED" ]; then
        MESSAGE="$MESSAGE\n\n📦 <b>Обновлено:</b>$UPGRADED"
    fi
    
    if [ ! -z "$REMOVED" ]; then
        MESSAGE="$MESSAGE\n\n🗑️ <b>Удалено:</b>$REMOVED"
    fi
    
    # Проверяем, нужна ли перезагрузка
    if echo "$LATEST_LOGS" | grep -q "reboot-required"; then
        MESSAGE="$MESSAGE\n\n⚠️ <b>Требуется перезагрузка!</b>"
    fi
    
    send_telegram "$MESSAGE"
    log "Уведомление отправлено"
    
else
    log "Обновлений не найдено"
fi

log "=== Проверка завершена ==="
