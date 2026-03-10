# 🤖 Server Management Bot

Telegram бот для управления Linux сервером.

## 📋 Возможности

- 📊 **Мониторинг сервера** - CPU, RAM, диск, аптайм
- 🔄 **Обновление системы** - проверка и установка обновлений
- 🏓 **Ping** - проверка доступности хостов
- 🔐 **Генератор паролей** - создание безопасных паролей
- 🔄 **Перезагрузка** - удаленная перезагрузка сервера
- :up **Контроль сроков аренды** - бот напомнит заранее о скором завершении аренды сервера

## 🚀 Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/GigaBlyate/server-bot.git
cd server-bot
```

2. Создание виртуального окружения:
```bash
python3 -m venv venv
source venv/bin/activate
```
3. Установка зависимостей:
```bash
pip install -r requirements.txt
```
4. Настройка конфигурации:
```bash
cp config.example.py config.py
nano config.py
```
Укажите:

TOKEN — токен от @BotFather

ADMIN_CHAT_ID — ваш Telegram ID (узнать у @userinfobot)

SERVER_NAME — название вашего сервера

5. Настройка прав sudo:
```bash
sudo visudo -f /etc/sudoers.d/bot
```
Добавьте строку (замените `username` на ваше имя пользователя):
```text
username ALL=(ALL) NOPASSWD: ALL
```
6. Запуск бота:
```bash
python bot.py
```
Автоматический запуск (systemd) что бы бот автоматически запускался после перезагрузки сервера:
```bash
sudo nano /etc/systemd/system/server-bot.service
```
Вставить в этот файл:
```text
[Unit]
Description=Server Management Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/server-bot
ExecStart=/home/YOUR_USERNAME/server-bot/venv/bin/python /home/YOUR_USERNAME/server-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
Затем:
```bash
sudo systemctl daemon-reload
sudo systemctl start server-bot
sudo systemctl enable server-bot
```
Автоматические уведомления об обновлениях
```bash
# Настройка прав на чтение лога
sudo chmod 644 /var/log/unattended-upgrades/unattended-upgrades.log
sudo chmod 755 /var/log/unattended-upgrades/

# Добавление в crontab
crontab -e
```
Добавьте строку (числа 30 и 5 это время по серверу. Сейчас стоит 5:30 утра. Если хотите другое время, то меняйте эти числа): 
```text
30 5 * * * /home/YOUR_USERNAME/server-bot/update-notifier.sh >> /home/YOUR_USERNAME/server-bot/update-notifier.log 2>&1
```
**Безопасность**
Доступ только по Telegram ID
Подтверждение опасных действий

