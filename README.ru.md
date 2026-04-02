<div align="center">

# G-PANEL

**Телеграм-бот для личного управления Linux-сервером**

<p>
  <img src="https://img.shields.io/badge/version-3.1.14-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.x-blue" alt="Python">
  <img src="https://img.shields.io/badge/platform-Debian%20%7C%20Ubuntu-6f42c1" alt="Platform">
  <img src="https://img.shields.io/badge/systemd-required-success" alt="systemd">
  <img src="https://img.shields.io/badge/telegram-bot-26A5E4" alt="Telegram Bot">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

[<img src="https://img.shields.io/badge/🇷🇺-Русский-red?style=for-the-badge" alt="Русский">](./README.ru.md)
[<img src="https://img.shields.io/badge/🇬🇧-English-blue?style=for-the-badge" alt="English">](./README.en.md)
[<img src="https://img.shields.io/badge/Wiki-Открыть-181717?style=for-the-badge" alt="Wiki">](https://github.com/GigaBlyate/server-bot/wiki)

</div>

---

## Что это

**G-PANEL** — это Telegram-бот для одного владельца, который помогает обслуживать сервер без постоянного входа по SSH.

Бот показывает состояние системы, помогает обновлять сервер, делать бэкапы, следить за VPS-арендой и контролировать важные сервисы — всё из личного Telegram-чата.

## Главные возможности

### 1. Живая панель сервера
Одна команда открывает краткую и понятную сводку: CPU, RAM, диск, сеть, uptime, версия ОС, публичный IP, геолокация и общая загрузка сервера.

### 2. Обновление и перезагрузка
Бот умеет проверять системные обновления, запускать обновление сервера и помогать безопасно перезагружать хост прямо из Telegram.

### 3. Бэкапы и подготовка к миграции
Есть обычный бэкап проекта и расширенный smart backup для переноса на другой сервер. Архивы можно хранить локально и выгружать в Google Drive.

### 4. Контроль VPS и трафика
Бот хранит список VPS, напоминает о продлении, считает дни до окончания и помогает отслеживать лимит трафика по текущему периоду.

### 5. Мониторинг ключевых сервисов
Автоматически находит популярные сервисы и показывает их статус. Поддерживается ручное добавление своих `systemd`-юнитов, процессов и Docker-контейнеров.

### 6. Сертификаты и важные предупреждения
Показывает найденные TLS-сертификаты, отмечает те, что скоро истекают, и отправляет полезные ежедневные сводки по серверу.

### 7. Только личный доступ
Бот работает только для владельца и только в личном чате. Это делает управление сервером проще и безопаснее для повседневной работы.

## Для кого этот бот

- для владельцев VPS и выделенных серверов
- для администраторов, которым нужен быстрый контроль через Telegram
- для тех, кто хочет держать под рукой обновления, бэкапы и статусы сервисов

## Быстрая установка

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GigaBlyate/server-bot/main/install.sh)
```

> Рекомендуемая система: **Debian / Ubuntu** с `systemd`.

## Документация

Подробная настройка, примеры, расширенные сценарии и все дополнительные разделы будут поддерживаться в **Wiki** проекта.

**Перейти в Wiki:** [github.com/GigaBlyate/server-bot/wiki](https://github.com/GigaBlyate/server-bot/wiki)
