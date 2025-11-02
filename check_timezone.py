#!/usr/bin/env python3
"""Script to check timezone settings and job execution times."""

from src.database import get_db
from src.models import Schedule, PublishJob
from datetime import datetime
import pytz

def main():
    db = next(get_db())
    
    print("=" * 80)
    print("SCHEDULE INFORMATION")
    print("=" * 80)
    
    # Get all cron schedules
    schedules = db.query(Schedule).filter(Schedule.kind == 'cron').order_by(Schedule.id.desc()).limit(10).all()
    
    for s in schedules:
        print(f"\nSchedule ID: {s.id}")
        print(f"  Cron: {s.schedule_spec}")
        print(f"  Timezone: {s.timezone}")
        print(f"  Next run at (UTC): {s.next_run_at}")
        print(f"  Last run at (UTC): {s.last_run_at}")
        print(f"  Enabled: {s.enabled}")
        
        if s.next_run_at and s.timezone:
            try:
                tz = pytz.timezone(s.timezone)
                next_utc = pytz.UTC.localize(s.next_run_at) if s.next_run_at.tzinfo is None else s.next_run_at
                next_local = next_utc.astimezone(tz)
                print(f"  Next run at (local): {next_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            except Exception as e:
                print(f"  Error converting timezone: {e}")
    
    print("\n" + "=" * 80)
    print("JOB #109 INFORMATION")
    print("=" * 80)
    
    job = db.query(PublishJob).filter(PublishJob.id == 109).first()
    if job:
        print(f"\nJob ID: {job.id}")
        print(f"Status: {job.status}")
        print(f"Planned At (UTC): {job.planned_at}")
        print(f"Started At (UTC): {job.started_at}")
        print(f"Finished At (UTC): {job.finished_at}")
        print(f"Schedule ID: {job.schedule_id}")
        
        # Get the schedule for this job
        schedule = db.query(Schedule).filter(Schedule.id == job.schedule_id).first()
        if schedule:
            print(f"\nAssociated Schedule:")
            print(f"  Cron: {schedule.schedule_spec}")
            print(f"  Timezone: {schedule.timezone}")
            
            # Convert planned_at to Central Time
            if job.planned_at:
                tz_ct = pytz.timezone('America/Chicago')
                planned_utc = pytz.UTC.localize(job.planned_at) if job.planned_at.tzinfo is None else job.planned_at
                planned_ct = planned_utc.astimezone(tz_ct)
                print(f"\nPlanned At (CT): {planned_ct.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                
                # Check what time the cron should have triggered
                if schedule.schedule_spec == "12 7 * * *":
                    print(f"\nExpected time for cron '12 7 * * *' in {schedule.timezone}:")
                    try:
                        tz_schedule = pytz.timezone(schedule.timezone)
                        # For 2025-11-02, 7:12 AM in the schedule timezone
                        target_date = datetime(2025, 11, 2, 7, 12, 0)
                        # Check if DST is in effect
                        if tz_schedule == pytz.timezone('America/Chicago'):
                            # November 2, 2025 is after DST ends (DST ends Nov 2, 2025 at 2 AM)
                            # So we're in CST, not CDT
                            naive_local = tz_schedule.localize(target_date, is_dst=False)
                            utc_equivalent = naive_local.astimezone(pytz.UTC).replace(tzinfo=None)
                            print(f"  7:12 AM {schedule.timezone} on 2025-11-02 = {utc_equivalent} UTC")
                            print(f"  Job planned_at = {job.planned_at}")
                            print(f"  Difference: {(job.planned_at - utc_equivalent).total_seconds() / 3600:.1f} hours")
                    except Exception as e:
                        print(f"  Error: {e}")
    else:
        print("Job #109 not found")
    
    print("\n" + "=" * 80)
    print("ENVIRONMENT CHECK")
    print("=" * 80)
    import os
    from src.utils.timezone_utils import get_default_timezone
    print(f"DEFAULT_TIMEZONE env var: {os.getenv('DEFAULT_TIMEZONE', 'not set')}")
    print(f"get_default_timezone() returns: {get_default_timezone()}")

if __name__ == "__main__":
    main()

