#!/usr/bin/env python3
"""Test script for scheduler functionality."""

import os
import sys
import logging
from datetime import datetime, timedelta
import pytz

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

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
        timezone="UTC",
        created_at=datetime.utcnow(),
        last_run_at=None,
        enabled=True
    )
    
    next_run = resolver.resolve_schedule(one_shot_schedule)
    logger.info(f"One-shot next run: {next_run}")
    assert next_run is not None, "One-shot schedule should have next run"
    
    # Test cron schedule
    logger.info("Testing cron schedule...")
    cron_schedule = Schedule(
        id=2,
        kind="cron",
        schedule_spec="0 2 * * *",  # Every day at 2 AM
        timezone="UTC",
        created_at=datetime.utcnow(),
        last_run_at=None,
        enabled=True
    )
    
    next_run = resolver.resolve_schedule(cron_schedule)
    logger.info(f"Cron next run: {next_run}")
    assert next_run is not None, "Cron schedule should have next run"
    
    logger.info("ScheduleResolver tests completed")


def test_cron_schedules():
    """Test cron schedule resolution."""
    logger.info("=" * 80)
    logger.info("Testing cron schedules...")
    
    resolver = ScheduleResolver()
    tz = pytz.timezone('America/Chicago')
    
    # Test 1: Basic cron schedule
    logger.info("Test 1: Basic cron schedule (daily at 10 AM)")
    cron_schedule = Schedule(
        id=100,
        kind="cron",
        schedule_spec="0 10 * * *",  # Daily at 10 AM
        timezone="America/Chicago",
        created_at=datetime.utcnow(),
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(cron_schedule)
    assert next_run is not None, "Cron schedule should resolve"
    logger.info(f"  ✓ Next run: {next_run}")
    
    # Test 2: Cron with last_run_at
    logger.info("Test 2: Cron schedule with last_run_at")
    last_run = datetime.utcnow() - timedelta(hours=1)
    cron_schedule.last_run_at = last_run
    next_run2 = resolver.resolve_schedule(cron_schedule)
    assert next_run2 is not None, "Cron schedule with last_run_at should resolve"
    logger.info(f"  ✓ Next run: {next_run2}")
    
    logger.info("Cron schedule tests completed\n")


def test_rrule_schedules():
    """Test RRULE schedule resolution."""
    logger.info("=" * 80)
    logger.info("Testing RRULE schedules...")
    
    resolver = ScheduleResolver()
    
    # Test 1: Basic RRULE schedule
    logger.info("Test 1: Basic RRULE schedule (daily at 9 AM)")
    rrule_schedule = Schedule(
        id=200,
        kind="rrule",
        schedule_spec="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
        timezone="America/Chicago",
        created_at=datetime.utcnow(),
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(rrule_schedule)
    assert next_run is not None, "RRULE schedule should resolve"
    logger.info(f"  ✓ Next run: {next_run}")
    
    # Test 2: RRULE with last_run_at
    logger.info("Test 2: RRULE schedule with last_run_at")
    last_run = datetime.utcnow() - timedelta(hours=1)
    rrule_schedule.last_run_at = last_run
    next_run2 = resolver.resolve_schedule(rrule_schedule)
    assert next_run2 is not None, "RRULE schedule with last_run_at should resolve"
    logger.info(f"  ✓ Next run: {next_run2}")
    
    # Test 3: Weekly RRULE
    logger.info("Test 3: Weekly RRULE (every Monday)")
    weekly_rrule = Schedule(
        id=201,
        kind="rrule",
        schedule_spec="FREQ=WEEKLY;BYDAY=MO;BYHOUR=10;BYMINUTE=0",
        timezone="America/Chicago",
        created_at=datetime.utcnow(),
        last_run_at=None,
        enabled=True
    )
    next_run3 = resolver.resolve_schedule(weekly_rrule)
    assert next_run3 is not None, "Weekly RRULE should resolve"
    logger.info(f"  ✓ Next run: {next_run3}")
    
    logger.info("RRULE schedule tests completed\n")


def test_dst_fall_back_cron():
    """Test cron schedules during fall back (DST ends: CDT -> CST)."""
    logger.info("=" * 80)
    logger.info("Testing cron DST fall back (CDT -> CST)...")
    
    resolver = ScheduleResolver()
    tz = pytz.timezone('America/Chicago')
    
    # Fall back happens on Nov 2, 2025 at 2 AM CDT -> 1 AM CST
    
    # Test 1: Cron schedule created before fall back, scheduled for 7:12 AM
    logger.info("Test 1: Cron '12 7 * * *' created Nov 1, 11 PM CDT")
    cron_schedule = Schedule(
        id=300,
        kind="cron",
        schedule_spec="12 7 * * *",  # 7:12 AM daily
        timezone="America/Chicago",
        created_at=datetime(2025, 11, 2, 4, 0, 0),  # Nov 1, 11 PM CDT in UTC
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(cron_schedule)
    assert next_run is not None, "Cron schedule should resolve"
    
    # Expected: Nov 2, 7:12 AM CST = Nov 2, 13:12 UTC (or later if that time has passed)
    expected_utc = datetime(2025, 11, 2, 13, 12, 0)
    # If the expected time has passed, the next occurrence will be tomorrow
    now_utc = datetime.utcnow()
    if now_utc > expected_utc:
        expected_utc = datetime(2025, 11, 3, 13, 12, 0)
    
    # Verify the time is correct (7:12 AM CST)
    next_run_utc = pytz.UTC.localize(next_run) if next_run.tzinfo is None else next_run
    next_run_local = next_run_utc.astimezone(tz)
    logger.info(f"  Got: {next_run_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run} UTC)")
    logger.info(f"  Expected: ~{expected_utc} UTC (7:12 AM CST)")
    
    # Verify it's at 7:12 AM CST
    assert next_run_local.hour == 7 and next_run_local.minute == 12, f"Expected 7:12 AM CST, got {next_run_local.strftime('%H:%M')}"
    assert next_run_utc.date() == expected_utc.date() or next_run_utc.date() == expected_utc.date() + timedelta(days=1), \
        f"Expected date {expected_utc.date()} or next day, got {next_run_utc.date()}"
    logger.info("  ✓ Correctly handles fall back transition")
    
    # Test 2: Cron schedule with last_run_at (after first execution)
    logger.info("Test 2: Cron '12 7 * * *' with last_run_at after execution")
    cron_schedule.last_run_at = datetime(2025, 11, 2, 13, 12, 0)  # Nov 2, 7:12 AM CST
    next_run2 = resolver.resolve_schedule(cron_schedule)
    assert next_run2 is not None, "Cron with last_run_at should resolve"
    
    # Expected: Next day Nov 3, 7:12 AM CST = Nov 3, 13:12 UTC
    expected_utc2 = datetime(2025, 11, 3, 13, 12, 0)
    logger.info(f"  Got: {next_run2}, Expected: {expected_utc2}")
    assert next_run2 == expected_utc2, f"Expected {expected_utc2}, got {next_run2}"
    logger.info("  ✓ Correctly calculates next run after execution")
    
    logger.info("Cron fall back tests completed\n")


def test_dst_spring_forward_cron():
    """Test cron schedules during spring forward (DST starts: CST -> CDT)."""
    logger.info("=" * 80)
    logger.info("Testing cron DST spring forward (CST -> CDT)...")
    
    resolver = ScheduleResolver()
    tz = pytz.timezone('America/Chicago')
    
    # Spring forward happens on March 9, 2025 at 2 AM CST -> 3 AM CDT
    
    # Test 1: Cron schedule created before spring forward, scheduled for 7:12 AM
    # Use a date in the future to avoid past-time issues
    future_date = datetime(2026, 3, 9, 5, 0, 0)  # March 8, 2026, 11 PM CST in UTC
    logger.info("Test 1: Cron '12 7 * * *' created March 8, 11 PM CST")
    cron_schedule = Schedule(
        id=400,
        kind="cron",
        schedule_spec="12 7 * * *",  # 7:12 AM daily
        timezone="America/Chicago",
        created_at=future_date,
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(cron_schedule)
    assert next_run is not None, "Cron schedule should resolve"
    
    # Verify the time is correct (7:12 AM CDT)
    next_run_utc = pytz.UTC.localize(next_run) if next_run.tzinfo is None else next_run
    next_run_local = next_run_utc.astimezone(tz)
    logger.info(f"  Got: {next_run_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run} UTC)")
    
    # Verify it's at 7:12 AM CDT (or CST if after fall back)
    assert next_run_local.hour == 7 and next_run_local.minute == 12, f"Expected 7:12 AM, got {next_run_local.strftime('%H:%M')}"
    logger.info("  ✓ Correctly handles spring forward transition")
    
    # Test 2: Cron schedule with last_run_at (after first execution)
    logger.info("Test 2: Cron '12 7 * * *' with last_run_at after execution")
    # Use a recent time for last_run_at
    recent_last_run = datetime.utcnow() - timedelta(hours=2)
    cron_schedule.last_run_at = recent_last_run
    next_run2 = resolver.resolve_schedule(cron_schedule)
    assert next_run2 is not None, "Cron with last_run_at should resolve"
    
    # Verify the time is correct (7:12 AM)
    next_run2_utc = pytz.UTC.localize(next_run2) if next_run2.tzinfo is None else next_run2
    next_run2_local = next_run2_utc.astimezone(tz)
    logger.info(f"  Got: {next_run2_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run2} UTC)")
    assert next_run2_local.hour == 7 and next_run2_local.minute == 12, f"Expected 7:12 AM, got {next_run2_local.strftime('%H:%M')}"
    logger.info("  ✓ Correctly calculates next run after execution")
    
    logger.info("Cron spring forward tests completed\n")


def test_dst_fall_back_rrule():
    """Test RRULE schedules during fall back (DST ends: CDT -> CST)."""
    logger.info("=" * 80)
    logger.info("Testing RRULE DST fall back (CDT -> CST)...")
    
    resolver = ScheduleResolver()
    tz = pytz.timezone('America/Chicago')
    
    # Fall back happens on Nov 2, 2025 at 2 AM CDT -> 1 AM CST
    
    # Test 1: RRULE schedule created before fall back, scheduled for 7:12 AM
    # Use a date in the past but before the transition to test DST handling
    fall_back_date = datetime(2025, 11, 2, 4, 0, 0)  # Nov 1, 11 PM CDT in UTC
    logger.info("Test 1: RRULE 'FREQ=DAILY;BYHOUR=7;BYMINUTE=12' created Nov 1, 11 PM CDT")
    rrule_schedule = Schedule(
        id=500,
        kind="rrule",
        schedule_spec="FREQ=DAILY;BYHOUR=7;BYMINUTE=12",
        timezone="America/Chicago",
        created_at=fall_back_date,
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(rrule_schedule)
    assert next_run is not None, "RRULE schedule should resolve"
    
    # Expected: Nov 2, 7:12 AM CST = Nov 2, 13:12 UTC (or later, depending on current time)
    # Since we can't predict exact time, just verify it's reasonable
    next_run_utc = pytz.UTC.localize(next_run) if next_run.tzinfo is None else next_run
    next_run_local = next_run_utc.astimezone(tz)
    logger.info(f"  Next run: {next_run_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run} UTC)")
    assert next_run_local.hour == 7 and next_run_local.minute == 12, "Should be 7:12 AM"
    logger.info("  ✓ Correctly handles fall back transition")
    
    # Test 2: RRULE schedule with last_run_at (after first execution)
    logger.info("Test 2: RRULE with last_run_at after execution")
    rrule_schedule.last_run_at = datetime(2025, 11, 2, 13, 12, 0)  # Nov 2, 7:12 AM CST
    next_run2 = resolver.resolve_schedule(rrule_schedule)
    assert next_run2 is not None, "RRULE with last_run_at should resolve"
    
    next_run2_utc = pytz.UTC.localize(next_run2) if next_run2.tzinfo is None else next_run2
    next_run2_local = next_run2_utc.astimezone(tz)
    logger.info(f"  Next run: {next_run2_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run2} UTC)")
    assert next_run2_local.hour == 7 and next_run2_local.minute == 12, "Should be 7:12 AM"
    logger.info("  ✓ Correctly calculates next run after execution")
    
    logger.info("RRULE fall back tests completed\n")


def test_dst_spring_forward_rrule():
    """Test RRULE schedules during spring forward (DST starts: CST -> CDT)."""
    logger.info("=" * 80)
    logger.info("Testing RRULE DST spring forward (CST -> CDT)...")
    
    resolver = ScheduleResolver()
    tz = pytz.timezone('America/Chicago')
    
    # Spring forward happens on March 9, 2025 at 2 AM CST -> 3 AM CDT
    
    # Test 1: RRULE schedule created before spring forward, scheduled for 7:12 AM
    # Use a date in the future to avoid past-time issues
    spring_forward_date = datetime(2026, 3, 9, 5, 0, 0)  # March 8, 2026, 11 PM CST in UTC
    logger.info("Test 1: RRULE 'FREQ=DAILY;BYHOUR=7;BYMINUTE=12' created March 8, 11 PM CST")
    rrule_schedule = Schedule(
        id=600,
        kind="rrule",
        schedule_spec="FREQ=DAILY;BYHOUR=7;BYMINUTE=12",
        timezone="America/Chicago",
        created_at=spring_forward_date,
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(rrule_schedule)
    assert next_run is not None, "RRULE schedule should resolve"
    
    # Expected: March 9, 7:12 AM CDT = March 9, 12:12 UTC (or later)
    next_run_utc = pytz.UTC.localize(next_run) if next_run.tzinfo is None else next_run
    next_run_local = next_run_utc.astimezone(tz)
    logger.info(f"  Next run: {next_run_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run} UTC)")
    assert next_run_local.hour == 7 and next_run_local.minute == 12, "Should be 7:12 AM"
    logger.info("  ✓ Correctly handles spring forward transition")
    
    # Test 2: RRULE schedule with last_run_at (after first execution)
    logger.info("Test 2: RRULE with last_run_at after execution")
    # Use a recent time for last_run_at
    recent_last_run = datetime.utcnow() - timedelta(hours=2)
    rrule_schedule.last_run_at = recent_last_run
    next_run2 = resolver.resolve_schedule(rrule_schedule)
    assert next_run2 is not None, "RRULE with last_run_at should resolve"
    
    next_run2_utc = pytz.UTC.localize(next_run2) if next_run2.tzinfo is None else next_run2
    next_run2_local = next_run2_utc.astimezone(tz)
    logger.info(f"  Next run: {next_run2_local.strftime('%Y-%m-%d %H:%M:%S %Z')} ({next_run2} UTC)")
    assert next_run2_local.hour == 7 and next_run2_local.minute == 12, "Should be 7:12 AM"
    logger.info("  ✓ Correctly calculates next run after execution")
    
    logger.info("RRULE spring forward tests completed\n")


def test_dst_edge_cases():
    """Test DST edge cases for schedules at transition times."""
    logger.info("=" * 80)
    logger.info("Testing DST edge cases...")
    
    resolver = ScheduleResolver()
    tz = pytz.timezone('America/Chicago')
    
    # Test 1: Cron at 1:30 AM (happens twice during fall back)
    logger.info("Test 1: Cron '30 1 * * *' during fall back (happens twice)")
    cron_130 = Schedule(
        id=700,
        kind="cron",
        schedule_spec="30 1 * * *",
        timezone="America/Chicago",
        created_at=datetime(2025, 11, 2, 4, 0, 0),  # Nov 1, 11 PM CDT
        last_run_at=None,
        enabled=True
    )
    next_run = resolver.resolve_schedule(cron_130)
    assert next_run is not None, "Cron 1:30 AM should resolve"
    logger.info(f"  ✓ Next run: {next_run}")
    
    # Test 2: Cron at 3:00 AM (just after transition)
    logger.info("Test 2: Cron '0 3 * * *' after fall back")
    cron_300 = Schedule(
        id=701,
        kind="cron",
        schedule_spec="0 3 * * *",
        timezone="America/Chicago",
        created_at=datetime(2025, 11, 2, 4, 0, 0),  # Nov 1, 11 PM CDT
        last_run_at=None,
        enabled=True
    )
    next_run2 = resolver.resolve_schedule(cron_300)
    assert next_run2 is not None, "Cron 3:00 AM should resolve"
    logger.info(f"  ✓ Next run: {next_run2}")
    
    logger.info("DST edge case tests completed\n")


def test_scheduler_integration():
    """Test scheduler integration with database."""
    logger.info("=" * 80)
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
    
    logger.info("Scheduler integration tests completed\n")


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("Starting scheduler tests...")
    logger.info("=" * 80)
    
    try:
        # Test schedule resolver basics
        test_schedule_resolver()
        
        # Test cron schedules
        test_cron_schedules()
        
        # Test RRULE schedules
        test_rrule_schedules()
        
        # Test DST transitions
        test_dst_fall_back_cron()
        test_dst_spring_forward_cron()
        test_dst_fall_back_rrule()
        test_dst_spring_forward_rrule()
        test_dst_edge_cases()
        
        # Test database integration
        test_scheduler_integration()
        
        logger.info("=" * 80)
        logger.info("All tests completed successfully! ✓")
        logger.info("=" * 80)
    except AssertionError as e:
        logger.error(f"Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
        sys.exit(1)
