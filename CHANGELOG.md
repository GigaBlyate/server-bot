# CHANGELOG

## 3.1.12
- traffic: switched package accounting to calendar-month billing periods anchored to the service activation date
- traffic: added automatic period rollover, period seed synchronization from hoster data, and correct remaining package calculation
- traffic: added Settings -> Traffic limit controls for package size, activation date, overage price, period sync and manual period reset
- traffic: added Back and Main menu buttons after traffic package input
- dashboard: added background automatic checks for server and bot updates with current status in the main menu
- dashboard: version now shows when bot updates are available, and system updates are reflected automatically

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
