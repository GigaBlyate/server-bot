# CHANGELOG

## 3.1.13

- Исправлен расчёт общего трафика: показатель "всего" теперь хранится как монотонный накопительный счётчик и не отстаёт от трафика за период после reboot.


- key services: manual add now validates real systemd services, real processes and real Docker containers before saving
- key services: added Back and Main Menu navigation after manual add and after failed lookup
- key services: synced main menu service list with auto-detected services and expanded rescan coverage for common service paths
- logging: benign Telegram "Message is not modified" events moved out of normal info noise

## 3.1.11
- dashboard: auto-detect OS name and installed version, hide hostname from main menu
- dashboard: fixed updates status refresh after successful system upgrade
- dashboard: expanded traffic summary with total, yesterday, current period, and package remainder
- dashboard: added concise load status with color indication
- dashboard: added last-backup age to main menu
- services: automatic discovery of key services, including popular VPN services, MTProto, Xray-family, Docker, databases, and web stacks
- settings: added simple manual key-service management and optional Docker access flow for service detection
- install: synced version bump for 3.1.11

## 3.1.9
- telemetry: stable server_uid + hourly heartbeat + active bots now
- installer: mandatory telemetry agreement flow with detailed text
- site: hidden contact email, anti-spam form, agreement modal, simpler privacy presentation
- updater: fixed current version output when no updates are available
