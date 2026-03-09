# Server Management Bot
Telegram бот для управления Linux сервером. 
Позволяет отслеживать состояние системы, выполнять обновления, перезагружать сервер, проверять доступность хостов и генерировать пароли.

Возможности
- Мониторинг ресурсов сервера (CPU, RAM, диск, аптайм)
- Проверка доступных обновлений и их установка
- Удаленная перезагрузка сервера (с подтверждением)
- Проверка связи с хостами (ping test)
- Генератор случайных паролей (просто полезная фича)

Проверка работоспособности команд и прав sudo

## Установка
1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/GigaBlyate/server-bot.git
   ```
2. Создание виртуального окружения и установка зависимостей
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Настройка конфигурации
Скопируйте файл с примером конфигурации и отредактируйте его:

   ```bash
   cp config.example.py config.py
   nano config.py
   ```
Укажите следующие параметры:

- TOKEN — токен вашего Telegram бота, полученный у @BotFather
- ADMIN_CHAT_ID — ваш Telegram ID (можно узнать у @userinfobot)
- SERVER_NAME — название сервера (например, VPS, HomeServer и т.п.)

4. Настройка прав sudo
Для выполнения команд обновления и перезагрузки боту требуется доступ к sudo без ввода пароля.
Создайте файл с правилами:
   ```bash
   sudo visudo -f /etc/sudoers.d/bot
   ```
Добавьте в него следующую строку (замените username на имя вашего пользователя):
```text
   username ALL=(ALL) NOPASSWD: ALL
```

5. Запуск бота
   ```bash
   python bot.py
   ```
Если всё настроено правильно, бот запустится и будет отвечать на команды в Telegram.

Чтобы бот запускался автоматически после перезагрузки сервера, создайте systemd-сервис.

1. Создание сервиса
   ```bash
   sudo nano /etc/systemd/system/server-bot.service
   ```
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
   ```
   
## Автоматические уведомления об обновлениях (если нужно)

Бот может присылать ежедневный отчёт о том, были ли установлены обновления.

1. Настройка автоматических обновлений системы
Убедитесь, что на сервере установлен и настроен пакет unattended-upgrades:

   ```bash
   sudo apt update
   sudo apt install unattended-upgrades -y
   sudo systemctl enable --now unattended-upgrades
   ```
2. Добавление задачи в crontab
   Откройте редактор cron:
   ```bash
   crontab -e
   ```
Добавьте следующую строку для запуска скрипта уведомлений каждый день в заданное время (напрмер в 8:00 утра):
Что бы изменить время, нужно именить первые 3 цифры, где 00 это минуты, 8 это часы. Тут пишем свое время.
```text
00 8 * * * /home/username/server-bot/update-notifier.sh >> /home/username/server-bot/update-notifier.log 2>&1
```

Убедитесь, что путь к скрипту указан верно, а сам скрипт имеет права на выполнение:

   ```bash
   chmod +x /home/username/server-bot/update-notifier.sh
```

Команды бота
| Команда       | Описание                          |
|---------------|-----------------------------------|
| `/start`      | Главное меню                      |
| `/status`     | Статус сервера                    |
| `/reboot`     | Перезагрузка (с подтверждением)   |
| `/update`     | Проверка доступных обновлений и их установка |
| `/ping`       | Проверка связи с хостами          |
| `/password`   | Генерация пароля (после password напишите число от 5 до 64, что будет равно кол-ву символов в пароле |
| `/help`       | Список доступных команд           |
Безопасность
Доступ к боту ограничен одним администратором по Telegram ID

Все опасные действия (обновление, перезагрузка) требуют подтверждения




   
