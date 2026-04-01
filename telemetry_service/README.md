# G-PANEL Telemetry Service

Минимальный сервис анонимной статистики.

## Что собирается
- `install_id` — случайный идентификатор установки
- `first_seen`
- `last_seen`

## Что не собирается
- IP/hostname в базе
- имена серверов
- токены
- домены
- содержимое конфигов

## Эндпоинты
- `POST /api/telemetry/install`
- `POST /api/telemetry/heartbeat`
- `GET /api/public/stats`
- `GET /healthz`

## Как связать с ботом
В `.env` бота:
```env
TELEMETRY_URL=https://stats.your-domain.example
TELEMETRY_ENABLED=true
```

## Как связать с сайтом
Сайт уже ожидает публичный JSON на:
`/api/public/stats`

Самый удобный вариант — проксировать этот путь с сайта на telemetry service через nginx.

Пример:
```nginx
location /api/public/stats {
    proxy_pass http://127.0.0.1:8787/api/public/stats;
}

location /api/telemetry/ {
    proxy_pass http://127.0.0.1:8787/api/telemetry/;
}
```
