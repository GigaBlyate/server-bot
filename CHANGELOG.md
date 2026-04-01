## 3.1.14
- key services: manual add now validates real systemd units, live processes and existing docker containers before saving
- key services: added back and main menu buttons after manual add success/failure and in service monitor prompts
- key services: unified alias detection for popular services (x-ui/3x-ui, Xray/V2Ray, MySQL/MariaDB, MTProto/TeleMT and more)
- key services: status logic now distinguishes running, stopped and not found; dashboard and settings use the same detection source
- update: bot self-update restart now passes the service name to root helper
- install: root helper now supports both legacy subcommands and generic restart/status/logs actions
- logs: benign Telegram "Message is not modified" moved from INFO to DEBUG

# CHANGELOG

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
