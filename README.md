Server Management Bot
Telegram бот для управления Linux сервером. 
Позволяет отслеживать состояние системы, выполнять обновления, перезагружать сервер, проверять доступность хостов и генерировать пароли.

Возможности
Мониторинг ресурсов сервера (CPU, RAM, диск, аптайм)

Проверка доступных обновлений и их установка

Удаленная перезагрузка сервера

Проверка связи с хостами (ping)

Генератор случайных паролей

Проверка работоспособности команд и прав sudo

Установка
1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/GigaBlyate/server-bot.git
2. Создание виртуального окружения и установка зависимостей
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
3. Настройка конфигурации
Скопируйте файл с примером конфигурации и отредактируйте его:

   ```bash
   cp config.example.py config.py
   nano config.py
Укажите следующие параметры:

TOKEN — токен вашего Telegram бота, полученный у @BotFather

ADMIN_CHAT_ID — ваш Telegram ID (можно узнать у @userinfobot)

SERVER_NAME — название сервера (например, VPS, HomeServer и т.п.)

4. Настройка прав sudo
Для выполнения команд обновления и перезагрузки боту требуется доступ к sudo без ввода пароля.
Создайте файл с правилами:
   ```bash
   sudo visudo -f /etc/sudoers.d/bot
Добавьте в него следующую строку (замените username на имя вашего пользователя):
```text
   username ALL=(ALL) NOPASSWD: ALL
```

5. Запуск бота
   ```bash
   python bot.py
Если всё настроено правильно, бот запустится и будет отвечать на команды в Telegram.

Чтобы бот запускался автоматически после перезагрузки сервера, создайте systemd-сервис.

1. Создание сервиса
   ```bash
   sudo nano /etc/systemd/system/server-bot.service
Вставьте следующее содержимое (при необходимости измените путь к проекту и имя пользователя):

```text
ini
[Unit]
Description=Server Management Bot
After=network.target

[Service]
Type=simple
User=username # Исправьте username на имя пользователя
WorkingDirectory=/home/username/server-bot # Исправьте username на имя пользователя
ExecStart=/home/username/server-bot/venv/bin/python /home/username/server-bot/bot.py # Исправьте username на имя пользователя
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
2. Запуск и включение автозагрузки
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start server-bot
   sudo systemctl enable server-bot
   sudo systemctl status server-bot
   
Автоматические уведомления об обновлениях

Бот может присылать ежедневный отчёт о том, были ли установлены обновления.

1. Настройка автоматических обновлений системы
Убедитесь, что на сервере установлен и настроен пакет unattended-upgrades:

   ```bash
   sudo apt update
   sudo apt install unattended-upgrades -y
   sudo systemctl enable --now unattended-upgrades
2. Добавление задачи в crontab
3. 
Откройте редактор cron:

   ```bash
   crontab -e
Добавьте следующую строку для запуска скрипта уведомлений каждый день в 5:30 утра:

```text
30 5 * * * /home/username/server-bot/update-notifier.sh >> /home/username/server-bot/update-notifier.log 2>&1
```
Убедитесь, что путь к скрипту указан верно, а сам скрипт имеет права на выполнение:

   ```bash
   chmod +x /home/username/server-bot/update-notifier.sh
```

Команды бота

/start — главное меню

/status — информация о состоянии сервера

/update — проверка доступных обновлений и их установка

/reboot — перезагрузка сервера (с подтверждением)

/ping — проверка связи с хостами

/password — генерация случайного пароля

/test — проверка работоспособности команд и прав sudo

/help — список доступных команд

Безопасность

Доступ к боту ограничен одним администратором по Telegram ID

Все опасные действия (обновление, перезагрузка) требуют подтверждения

Конфигурационный файл с токеном не включён в репозиторий

Скрипты уведомлений не содержат токен — он читается из config.py
