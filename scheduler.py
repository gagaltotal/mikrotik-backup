import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from db import db, Schedule

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_status_queue = None
_app = None

def set_status_queue(q):
    global _status_queue
    _status_queue = q

def init_scheduler(app):
    global _scheduler, _app
    _app = app
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(
        jobstores={'default': MemoryJobStore()}, timezone='UTC'
    )
    _scheduler.start()
    return _scheduler

def _emit(router_id, status, message=''):
    if _status_queue:
        try:
            _status_queue.put_nowait(
                {'router_id': router_id, 'status': status, 'message': message}
            )
        except Exception:
            pass

def _job(router_id, backup_type, schedule_id):
    """Scheduled job entry-point with App Context."""
    if not _app:
        logger.error("Flask app not initialized in scheduler")
        return
    with _app.app_context():
        try:
            from app import perform_backup
            perform_backup(router_id, backup_type,
                           triggered_by=f'schedule:{schedule_id}',
                           schedule_id=schedule_id)
        except Exception as exc:
            logger.error(f'Scheduled backup failed (router={router_id}): {exc}')
            _emit(router_id, 'backup_failed', str(exc))

def _job_id(schedule_id: int) -> str:
    return f'backup_sched_{schedule_id}'

def add_schedule_job(sched_row: Schedule):
    if not _scheduler:
        return
    try:
        trigger = CronTrigger.from_crontab(sched_row.cron_expr)
        _scheduler.add_job(
            _job, trigger=trigger,
            args=[sched_row.router_id, sched_row.backup_type, sched_row.id],
            id=_job_id(sched_row.id), replace_existing=True,
        )
        job = _scheduler.get_job(_job_id(sched_row.id))
        if job and job.next_run_time:
            sched_row.next_run = job.next_run_time
            db.session.commit()
    except Exception as exc:
        logger.error(f'Failed to add schedule {sched_row.id}: {exc}')

def remove_schedule_job(schedule_id: int):
    if not _scheduler:
        return
    try:
        _scheduler.remove_job(_job_id(schedule_id))
    except Exception:
        pass

def reload_all():
    if not _scheduler or not _app:
        return
    with _app.app_context():
        try:
            for j in _scheduler.get_jobs():
                _scheduler.remove_job(j.id)
            for s in Schedule.query.filter_by(enabled=True).all():
                add_schedule_job(s)
        except Exception as e:
            logger.warning(f"Could not load schedules from DB (tables might not exist yet): {e}")

def shutdown():
    if _scheduler:
        _scheduler.shutdown(wait=False)