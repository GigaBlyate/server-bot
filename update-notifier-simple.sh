nano update-notifier-simple.sh
#!/bin/bash

# Конфигурация
BOT_TOKEN="TOKEN_BOT"
CHAT_ID="CHAT_ID"
SERVER_NAME="SERVER_NAME"
LOG_FILE="/var/log/unattended-upgrades/unattended-upgrades.log"

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$1" \
        -d "parse_mode=HTML" > /dev/null
}

# Получаем последние обновления из лога
LAST_UPDATES=$(sudo tail -20 "$LOG_FILE" | grep -E "upgrade|install|remove|auto-removed" | tail -5)

if [ ! -z "$LAST_UPDATES" ]; then
    DATE=$(date '+%Y-%m-%d %H:%M:%S')
    
    MESSAGE="🖥️ <b>$SERVER_NAME</b> - Отчёт об обновлениях
━━━━━━━━━━━━━━━━━━━━━
📅 $DATE

📋 <b>Последние изменения:</b>
\`\`\`
$LAST_UPDATES
\`\`\`"
    
    # Проверяем, нужна ли перезагрузка
    if [ -f /var/run/reboot-required ]; then
        MESSAGE="$MESSAGE\n⚠️ <b>Требуется перезагрузка!</b>"
    fi
    
    send_telegram "$MESSAGE"
    echo "✅ Уведомление отправлено"
else
    echo "❌ Нет новых обновлений в логе"
fi
