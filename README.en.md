<div align="center">

# G-PANEL

**Telegram bot for personal Linux server management**

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
[<img src="https://img.shields.io/badge/Wiki-Open-181717?style=for-the-badge" alt="Wiki">](https://github.com/GigaBlyate/server-bot/wiki)

</div>

---

## What it is

**G-PANEL** is a Telegram bot for a single owner who wants to manage a Linux server without constantly logging in over SSH.

It gives you a clean server overview, helps with updates, backups, VPS subscription tracking and service monitoring — all from a private Telegram chat.

## Main features

### 1. Live server dashboard
Open a compact dashboard with CPU, RAM, disk usage, network stats, uptime, OS version, public IP, geolocation and overall server load.

### 2. Updates and reboot control
The bot can check system updates, run server upgrades and help you safely reboot the host directly from Telegram.

### 3. Backups and migration support
It includes a regular project backup and a smarter backup mode for migration to another server. Archives can be kept locally or uploaded to Google Drive.

### 4. VPS and traffic tracking
Track your VPS entries, renewal dates, remaining days and traffic quota usage for the current billing period.

### 5. Key service monitoring
The bot automatically detects popular services and shows their status. You can also add your own `systemd` units, processes and Docker containers manually.

### 6. Certificates and useful alerts
It lists discovered TLS certificates, highlights the ones that are close to expiration and sends practical daily server summaries.

### 7. Owner-only access
The bot is designed for personal use: it works only for the owner and only in a private Telegram chat.

## Who it is for

- VPS and dedicated server owners
- admins who want quick Telegram-based control
- users who need updates, backups and service visibility in one place

## Quick install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GigaBlyate/server-bot/main/install.sh)
```

> Recommended platform: **Debian / Ubuntu** with `systemd`.

## Documentation

Full setup instructions, examples, advanced scenarios and additional documentation will be maintained in the project **Wiki**.

**Open Wiki:** [github.com/GigaBlyate/server-bot/wiki](https://github.com/GigaBlyate/server-bot/wiki)
