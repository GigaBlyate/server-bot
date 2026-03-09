# 🤖 Server Management Bot

Telegram бот для управления Linux сервером. Мониторинг ресурсов, обновление системы, ping и генератор паролей.

## 📋 Возможности

- 📊 **Мониторинг сервера** - CPU, RAM, диск, аптайм
- 🔄 **Обновление системы** - проверка и установка обновлений
- 🏓 **Ping** - проверка доступности хостов
- 🔐 **Генератор паролей** - создание безопасных паролей
- 🔄 **Перезагрузка** - удаленная перезагрузка сервера

## 🚀 Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/GigaBlyate/server-bot.git
cd server-bot

2. Создать виртуальное окружение и установить зависимости
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

3. Отредактировать файл конфигурации
cp config.example.py config.py
nano config.py
Вставьте свои данные:

TOKEN – токен от @BotFather

ADMIN_CHAT_ID – ваш Telegram ID (можно узнать у @userinfobot)

SERVER_NAME – название вашего сервера (любое)

4. Настроить sudo без пароля (для выполнения команд обновления/перезагрузки)
sudo visudo -f /etc/sudoers.d/bot

Добавьте строку (замените YOUR_MANE на имя вашего пользователя):
YOUR_NAME ALL=(ALL) NOPASSWD: ALL

5. Запустить бота вручную (для теста)
python bot.py

