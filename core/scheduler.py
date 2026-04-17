#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import time

from telegram.ext import Application

from core.db import get_setting
from services.fail2ban_service import fail2ban_monitor_job
from services.metrics import resource_monitor_job, sample_metrics_job
from services.reports import daily_report_job
from services.traffic_quota import traffic_quota_job
from services.vps_service import send_vps_expiry_notifications



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
    app.job_queue.run_repeating(fail2ban_monitor_job, interval=120, first=45, name='fail2ban-monitor')
    app.job_queue.run_repeating(send_vps_expiry_notifications, interval=21600, first=120, name='vps-expiry')
    schedule_daily_report_job(app)
