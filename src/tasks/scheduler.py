"""Celery tasks for scheduler automation."""

import logging
from datetime import datetime, timedelta
from typing import List

from src.celery_app import app
from src.database import get_db
from src.models import Schedule, PublishJob
from src.utils.redis_utils import acquire_dedupe_lock
from src.services.scheduler_service import ScheduleResolver
from src.services.variant_service import VariantSelector

logger = logging.getLogger(__name__)


@app.task(
    name="scheduler.tick",
    queue="scheduler",
    acks_late=True,
    task_ignore_result=True,
)
def scheduler_tick():
    """Main scheduler loop - runs every minute via Celery Beat."""
    logger.info("Starting scheduler tick")
    
    try:
        with get_db() as db:
            # IMPORTANT: Use SELECT ... FOR UPDATE SKIP LOCKED for safe multi-scheduler sharding
            # This allows multiple scheduler instances to safely share work without conflicts
            due_schedules = (
                db.query(Schedule)
                .filter(
                    Schedule.next_run_at <= datetime.utcnow(),
                    Schedule.enabled.is_(True)
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            
            logger.info(f"Found {len(due_schedules)} due schedules")
            
            scheduler_resolver = ScheduleResolver()
            variant_selector = VariantSelector(db)  # NEW: Variant selection service
            jobs_created = 0
            
            for schedule in due_schedules:
                try:
                    planned_at = schedule.next_run_at
                    
                    # Redis dedupe guard (idempotent across multiple schedulers)
                    if not acquire_dedupe_lock(schedule.id, planned_at):
                        logger.info(f"Skipping schedule {schedule.id} - dedupe lock already exists")
                        continue
                    
                    # VARIANT SELECTION (NEW) - All within the same transaction
                    # Schedule row is already locked via WITH FOR UPDATE SKIP LOCKED
                    selected_variant = None
                    selection_seed = None
                    
                    if schedule.template_id:
                        # New template-based schedule
                        # select_variant returns both variant and seed (single generation)
                        selected_variant, selection_seed = variant_selector.select_variant(
                            schedule, 
                            planned_at
                        )
                        
                        if not selected_variant:
                            logger.error(
                                f"Schedule {schedule.id} has no active variants, skipping"
                            )
                            continue
                    # else: Legacy post_id schedule - handled in publish_post()
                    
                    # Create publish job (atomic with selection above)
                    # The UNIQUE constraint on (schedule_id, planned_at) prevents duplicates
                    job = PublishJob(
                        schedule_id=schedule.id,
                        planned_at=planned_at,
                        status="planned",
                        dedupe_key=f"{schedule.id}:{planned_at.isoformat()}",
                        variant_id=selected_variant.id if selected_variant else None,
                        selection_policy=schedule.selection_policy if schedule.template_id else None,
                        selection_seed=selection_seed,
                        selected_at=datetime.utcnow() if selected_variant else None,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(job)
                    db.flush()  # Get job.id
                    
                    # Record selection history AFTER job creation (so we have job_id)
                    # Always record if variant-based, regardless of no_repeat_window (for audit)
                    if selected_variant and schedule.template_id:
                        variant_selector.record_selection(
                            template_id=schedule.template_id,
                            variant_id=selected_variant.id,
                            schedule_id=schedule.id,
                            job_id=job.id,  # Now available after flush
                            planned_at=planned_at
                        )
                    
                    # Enqueue publish task with ETA via shared helper
                    from src.utils.job_queue import enqueue_publish_job
                    enqueue_publish_job(job.id, eta=planned_at)
                    
                    # Update last run time FIRST (before resolving next run)
                    # This ensures recurring schedules (rrule, cron) find the next occurrence
                    # after the current execution time, not the previous one
                    schedule.last_run_at = planned_at
                    
                    # Compute and persist next run time
                    # For recurring schedules, this will use last_run_at as the reference point
                    next_run_at = scheduler_resolver.resolve_schedule(schedule)
                    if next_run_at:
                        schedule.next_run_at = next_run_at
                        logger.info(f"Schedule {schedule.id} next run: {next_run_at}")
                    else:
                        # No next run time (e.g., one-shot that's done, or invalid schedule)
                        schedule.enabled = False
                        logger.info(f"Disabling schedule {schedule.id} - no next run time")
                    
                    schedule.updated_at = datetime.utcnow()
                    
                    jobs_created += 1
                    logger.info(f"Created job {job.id} for schedule {schedule.id}")
                    
                except Exception as e:
                    logger.error(f"Error processing schedule {schedule.id}: {str(e)}")
                    # Continue with other schedules even if one fails
                    continue
            
            # Commit all changes
            db.commit()
            logger.info(f"Scheduler tick completed. Created {jobs_created} jobs.")
            
    except Exception as e:
        logger.error(f"Scheduler tick failed: {str(e)}")
        raise


@app.task(
    name="scheduler.initialize_schedules",
    queue="scheduler",
    acks_late=True,
    task_ignore_result=True,
)
def initialize_schedules():
    """Initialize next_run_at for schedules that don't have it set."""
    logger.info("Initializing schedules without next_run_at")
    
    try:
        with get_db() as db:
            # Find schedules that don't have next_run_at set
            schedules_to_init = (
                db.query(Schedule)
                .filter(
                    Schedule.next_run_at.is_(None),
                    Schedule.enabled.is_(True)
                )
                .all()
            )
            
            logger.info(f"Found {len(schedules_to_init)} schedules to initialize")
            
            scheduler_resolver = ScheduleResolver()
            initialized_count = 0
            
            for schedule in schedules_to_init:
                try:
                    next_run_at = scheduler_resolver.resolve_schedule(schedule)
                    if next_run_at:
                        schedule.next_run_at = next_run_at
                        schedule.updated_at = datetime.utcnow()
                        initialized_count += 1
                        logger.info(f"Initialized schedule {schedule.id} with next_run_at: {next_run_at}")
                    else:
                        # Disable schedule if it can't be resolved
                        schedule.enabled = False
                        logger.warning(f"Disabled schedule {schedule.id} - could not resolve next run time")
                        
                except Exception as e:
                    logger.error(f"Error initializing schedule {schedule.id}: {str(e)}")
                    continue
            
            db.commit()
            logger.info(f"Initialized {initialized_count} schedules")
            
    except Exception as e:
        logger.error(f"Schedule initialization failed: {str(e)}")
        raise


@app.task(
    name="scheduler.cleanup_orphaned_jobs",
    queue="scheduler",
    acks_late=True,
    task_ignore_result=True,
)
def cleanup_orphaned_jobs_task():
    """Periodic task to cleanup and re-enqueue orphaned jobs."""
    logger.info("Running orphaned jobs cleanup")
    
    try:
        from src.utils.job_cleanup import cleanup_orphaned_jobs
        cleanup_stats = cleanup_orphaned_jobs(timeout_minutes=5)
        
        if cleanup_stats["found"] > 0:
            logger.info(
                f"Cleanup completed: re-enqueued {cleanup_stats['re_enqueued']} "
                f"orphaned jobs ({cleanup_stats['failed']} failed), "
                f"job IDs: {cleanup_stats['job_ids']}"
            )
        else:
            logger.debug("No orphaned jobs found")
            
    except Exception as e:
        logger.error(f"Orphaned jobs cleanup failed: {str(e)}", exc_info=True)
        raise


@app.task(
    name="scheduler.health_check",
    queue="scheduler",
    acks_late=True,
    task_ignore_result=True,
)
def scheduler_health_check():
    """Health check for scheduler service."""
    logger.info("Running scheduler health check")
    
    try:
        with get_db() as db:
            # Check for schedules that should have run but haven't
            overdue_schedules = (
                db.query(Schedule)
                .filter(
                    Schedule.next_run_at < datetime.utcnow() - timedelta(minutes=5),  # 5 minutes grace period
                    Schedule.enabled.is_(True)
                )
                .count()
            )
            
            # Check for stuck jobs
            stuck_jobs = (
                db.query(PublishJob)
                .filter(
                    PublishJob.status == "running",
                    PublishJob.started_at < datetime.utcnow() - timedelta(minutes=10)  # 10 minutes timeout
                )
                .count()
            )
            
            logger.info(f"Health check: {overdue_schedules} overdue schedules, {stuck_jobs} stuck jobs")
            
            # TODO: Add alerting if thresholds are exceeded
            if overdue_schedules > 10:
                logger.warning(f"High number of overdue schedules: {overdue_schedules}")
            
            if stuck_jobs > 5:
                logger.warning(f"High number of stuck jobs: {stuck_jobs}")
                
    except Exception as e:
        logger.error(f"Scheduler health check failed: {str(e)}")
        raise
