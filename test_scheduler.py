#!/usr/bin/env python3
"""Test script for scheduler functionality."""

import os
import sys
import logging
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.database import get_db
from src.models import Schedule, Post
from src.services.scheduler_service import ScheduleResolver

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_schedule_resolver():
    """Test the schedule resolver with different schedule types."""
    logger.info("Testing ScheduleResolver...")
    
    resolver = ScheduleResolver()
    
    # Test one-shot schedule
    logger.info("Testing one-shot schedule...")
    one_shot_schedule = Schedule(
        id=1,
        kind="one_shot",
        schedule_spec=(datetime.utcnow() + timedelta(minutes=5)).isoformat(),
        timezone="UTC"
    )
    
    next_run = resolver.resolve_schedule(one_shot_schedule)
    logger.info(f"One-shot next run: {next_run}")
    
    # Test cron schedule
    logger.info("Testing cron schedule...")
    cron_schedule = Schedule(
        id=2,
        kind="cron",
        schedule_spec="0 */2 * * *",  # Every 2 hours
        timezone="UTC"
    )
    
    next_run = resolver.resolve_schedule(cron_schedule)
    logger.info(f"Cron next run: {next_run}")
    
    logger.info("ScheduleResolver tests completed")


def test_scheduler_integration():
    """Test scheduler integration with database."""
    logger.info("Testing scheduler integration...")
    
    try:
        with get_db() as db:
            # Check if we have any schedules
            schedules = db.query(Schedule).filter(Schedule.enabled.is_(True)).all()
            logger.info(f"Found {len(schedules)} enabled schedules")
            
            for schedule in schedules:
                logger.info(f"Schedule {schedule.id}: {schedule.kind} - {schedule.schedule_spec}")
                logger.info(f"  Next run: {schedule.next_run_at}")
                logger.info(f"  Last run: {schedule.last_run_at}")
                
                # Test resolver
                resolver = ScheduleResolver()
                next_run = resolver.resolve_schedule(schedule)
                logger.info(f"  Resolved next run: {next_run}")
                
    except Exception as e:
        logger.error(f"Database test failed: {str(e)}")


if __name__ == "__main__":
    logger.info("Starting scheduler tests...")
    
    # Test schedule resolver
    test_schedule_resolver()
    
    # Test database integration
    test_scheduler_integration()
    
    logger.info("All tests completed!")
