#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import time

from telegram.ext import Application

from core.db import get_setting
from services.metrics import resource_monitor_job, sample_metrics_job
from services.reports import daily_report_job
from services.telemetry import telemetry_enabled, telemetry_heartbeat_job, telemetry_startup_job
from services.traffic_quota import traffic_quota_job
from services.vps_service import send_vps_expiry_notifications
from services.updater import update_status_background_job



def schedule_daily_report_job(app: Application) -> None:
    if app.job_queue is None:
        return
    for job in app.job_queue.get_jobs_by_name('daily-report-job'):
        job.schedule_removal()

    raw_time = get_setting('report_time', '09:00')
    hour, minute = 9, 0
    try:
        hour, minute = [int(part) for part in raw_time.split(':', 1)]
    except Exception:
        pass

    app.job_queue.run_daily(
        daily_report_job,
        time=time(hour=hour, minute=minute),
        name='daily-report-job',
    )



def setup_jobs(app: Application) -> None:
    if app.job_queue is None:
        return
    monitor_interval = int(get_setting('monitor_interval', '60') or 60)
    app.job_queue.run_repeating(sample_metrics_job, interval=600, first=10, name='metrics-sample')
    app.job_queue.run_repeating(resource_monitor_job, interval=monitor_interval, first=20, name='resource-monitor')
    app.job_queue.run_repeating(traffic_quota_job, interval=900, first=60, name='traffic-quota')
    app.job_queue.run_repeating(send_vps_expiry_notifications, interval=21600, first=120, name='vps-expiry')
    app.job_queue.run_once(update_status_background_job, when=20, name='update-status-startup')
    app.job_queue.run_repeating(update_status_background_job, interval=7200, first=1800, name='update-status-refresh')
    if telemetry_enabled():
        app.job_queue.run_once(telemetry_startup_job, when=15, name='telemetry-startup')
        app.job_queue.run_repeating(
            telemetry_heartbeat_job,
            interval=60 * 60,
            first=10 * 60,
            name='telemetry-heartbeat',
        )
    schedule_daily_report_job(app)
