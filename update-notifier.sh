#!/bin/bash

# Конфигурация (заполнять внутри кавычек!!)
BOT_TOKEN="TOKEN"
CHAT_ID="CHAT_ID"
SERVER_NAME="NAME_SERVER"
LOG_FILE="/var/log/unattended-upgrades/unattended-upgrades.log"
HISTORY_FILE="/tmp/last_update_report.txt"

# Функция отправки в Telegram
send_telegram() {
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$message" \
        -d "parse_mode=HTML" > /dev/null
}

# Получаем текущую дату
CURRENT_DATE=$(date '+%Y-%m-%d')
CURRENT_TIME=$(date '+%H:%M:%S')

# Проверяем, были ли обновления за последние 24 часа
if [ -f "$LOG_FILE" ]; then
    # Ищем записи об установленных обновлениях за сегодня и вчера
    YESTERDAY=$(date -d "yesterday" '+%Y-%m-%d')
    
    # Проверяем успешные обновления
    UPDATES_FOUND=$(grep -E "Packages that were upgraded|All upgrades installed|Packages that were successfully auto-removed" "$LOG_FILE" | tail -10)
    
    # Проверяем удаление старых ядер
    KERNEL_REMOVED=$(grep "Packages that were successfully auto-removed" "$LOG_FILE" | tail -5)
    
    # Проверяем, была ли запланирована перезагрузка
    REBOOT_SCHEDULED=$(grep "reboot-required" "$LOG_FILE" | tail -5)
    
    if [ ! -z "$UPDATES_FOUND" ] || [ ! -z "$KERNEL_REMOVED" ]; then
        # Формируем сообщение
        MESSAGE="🖥️ <b>$SERVER_NAME</b> - Отчёт об обновлениях
━━━━━━━━━━━━━━━━━━━━━
📅 Дата: $CURRENT_DATE $CURRENT_TIME

"
        
        # Добавляем информацию об обновлениях
        if [ ! -z "$UPDATES_FOUND" ]; then
            # Подсчитываем примерное количество
            UPDATE_COUNT=$(grep "Packages that were upgraded" "$LOG_FILE" | tail -1 | grep -o "[0-9]\+" | head -1)
            if [ ! -z "$UPDATE_COUNT" ]; then
                MESSAGE="$MESSAGE📦 Установлено обновлений: <b>$UPDATE_COUNT</b>\n\n"
            fi
            
            # Пытаемся найти список обновлённых пакетов
            UPGRADE_LINE=$(grep "Packages that will be upgraded" "$LOG_FILE" | tail -1)
            if [ ! -z "$UPGRADE_LINE" ]; then
                PACKAGES=$(echo "$UPGRADE_LINE" | cut -d':' -f2- | cut -c1-200)
                MESSAGE="$MESSAGE📋 <b>Основные обновления:</b>\n$PACKAGES...\n\n"
            fi
        fi
        
        # Добавляем информацию об удалённых ядрах
        if [ ! -z "$KERNEL_REMOVED" ]; then
            REMOVED_KERNELS=$(echo "$KERNEL_REMOVED" | grep -o "linux-image-[^ ]*" | head -3)
            if [ ! -z "$REMOVED_KERNELS" ]; then
                MESSAGE="$MESSAGE🗑️ <b>Удалены старые ядра:</b>\n"
                while IFS= read -r kernel; do
                    MESSAGE="$MESSAGE• $kernel\n"
                done <<< "$REMOVED_KERNELS"
                MESSAGE="$MESSAGE\n"
            fi
        fi
        
        # Проверяем, нужна ли перезагрузка
        if [ -f /var/run/reboot-required ]; then
            MESSAGE="$MESSAGE⚠️ <b>Требуется перезагрузка!</b>\n"
            if [ ! -z "$REBOOT_SCHEDULED" ]; then
                MESSAGE="$MESSAGE🔜 Перезагрузка запланирована на завтра 05:30\n"
            else
                MESSAGE="$MESSAGEИспользуйте кнопку 🔄 Перезагрузка в меню бота.\n"
            fi
        else
            MESSAGE="$MESSAGE✅ Перезагрузка не требуется.\n"
        fi
        
        # Проверяем, не отправляли ли мы это уведомление
        if [ ! -f "$HISTORY_FILE" ] || [ "$(cat $HISTORY_FILE)" != "$UPDATES_FOUND" ]; then
            send_telegram "$MESSAGE"
            echo "$UPDATES_FOUND" > "$HISTORY_FILE"
            echo "✅ Уведомление отправлено"
        else
            echo "⏭️ Уведомление уже отправлялось"
        fi
    else
        echo "✅ Обновлений не найдено"
        # Отправляем уведомление раз в неделю, что всё ок
        DAY_OF_WEEK=$(date '+%u')
        HOUR=$(date '+%H')
        if [ "$DAY_OF_WEEK" = "1" ] && [ "$HOUR" = "06" ]; then
            send_telegram "🖥️ <b>$SERVER_NAME</b> - Проверка обновлений
━━━━━━━━━━━━━━━━━━━━━
✅ Система актуальна. Обновлений не найдено.
📅 Последняя проверка: $CURRENT_DATE $CURRENT_TIME"
        fi
    fi
else
    echo "❌ Файл лога не найден: $LOG_FILE"
    send_telegram "⚠️ <b>$SERVER_NAME</b>: Файл лога обновлений не найден!"
fi

# Дополнительно: проверяем свободное место на диске
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 85 ]; then
    send_telegram "⚠️ <b>$SERVER_NAME</b>: Внимание! На диске осталось мало места.
Использовано: $DISK_USAGE%"
fi
