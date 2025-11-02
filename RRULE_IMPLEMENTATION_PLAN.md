# RRULE Implementation Plan

## Overview

This document outlines the implementation plan for adding RRULE (iCal recurrence rule) support to the scheduler system. RRULE allows users to create complex recurring schedules that go beyond cron's capabilities, such as "every Monday, Wednesday, Friday" or "the first Monday of each month."

## Library Choice

**We will use `python-dateutil.rrule`** - already available in `requirements.txt`:
- ✅ **No new dependency needed** - `python-dateutil>=2.8.0` is already installed
- ✅ **RFC 5545 compliant** - Full iCal RRULE standard support
- ✅ **Well-maintained** - Widely used and actively maintained
- ✅ **Full feature support** - Handles all RRULE components (FREQ, COUNT, UNTIL, BYDAY, etc.)

**Import statement:**
```python
from dateutil.rrule import rrulestr
```

**Key function:** `rrulestr()` - Parses RRULE strings in iCal format and returns an `rrule` object for computing occurrences.

## Current State

### ✅ What's Already in Place
- ✅ Database model supports `kind="rrule"` in `Schedule` table
- ✅ `ScheduleResolver` class with stub `_resolve_rrule()` method
- ✅ Timezone support (`schedule.timezone` field)
- ✅ Test structure for RRULE (currently expects `None`)
- ✅ Scheduler infrastructure (Celery Beat, task queue, deduplication)

### ❌ What's Missing
- ❌ RRULE parsing and computation
- ❌ DTSTART handling (start date for recurrence)
- ❌ COUNT/UNTIL limit support
- ❌ Comprehensive RRULE test cases

## Implementation Strategy

### Phase 1: Core RRULE Parsing (Foundation)
**Goal**: Implement basic RRULE parsing using `python-dateutil.rrule`

**Tasks:**
1. Verify `python-dateutil` dependency (already in `requirements.txt`)
2. Implement `_resolve_rrule()` method in `ScheduleResolver`
3. Parse RRULE string from `schedule_spec`
4. Handle DTSTART (derive from schedule creation time or use `created_at`)
5. Compute next occurrence after current time (or `last_run_at`)
6. Convert to UTC for storage consistency

**Technical Details:**
- Use `dateutil.rrule.rrulestr()` to parse RRULE string
- If DTSTART not in RRULE, derive from `schedule.created_at` or current time
- Use `schedule.timezone` for timezone-aware calculations
- Handle missing/explicit DTSTART gracefully
- Return `None` if RRULE has expired (UNTIL passed, COUNT exhausted)

### Phase 2: Advanced RRULE Features
**Goal**: Support COUNT, UNTIL, BYDAY, BYMONTH, etc.

**Tasks:**
1. Support COUNT limit (stop after N occurrences)
2. Support UNTIL limit (stop before date)
3. Handle complex BY rules (BYDAY, BYMONTHDAY, BYMONTH, BYYEARDAY, BYWEEKNO, BYSETPOS)
4. Validate RRULE format and provide helpful error messages
5. Handle edge cases (leap years, invalid dates, etc.)

### Phase 3: Testing & Validation
**Goal**: Comprehensive test coverage

**Tasks:**
1. Unit tests for common RRULE patterns
2. Integration tests with scheduler tick
3. Edge case tests (invalid RRULE, expired rules, timezone handling)
4. Performance tests (large COUNT values)

### Phase 4: Documentation & API Updates
**Goal**: Update documentation and API to support RRULE

**Tasks:**
1. Update API documentation for RRULE format
2. Update IMPLEMENTATION_PLAN.md status
3. Update QUEUE.md with RRULE examples
4. Add RRULE validation in API endpoints

## Detailed Implementation

### Schedule Spec Format

The `schedule_spec` field will store an RRULE string. Two formats are supported:

#### Format 1: RRULE only (DTSTART inferred)
```
FREQ=DAILY;INTERVAL=1
FREQ=WEEKLY;BYDAY=MO,WE,FR
FREQ=MONTHLY;BYMONTHDAY=1
```

**Behavior:**
- DTSTART is inferred from `schedule.created_at` if available
- Otherwise uses current time when resolving

#### Format 2: Full iCal format with DTSTART
```
DTSTART:20240101T090000Z
RRULE:FREQ=DAILY;INTERVAL=1
```

**Behavior:**
- Parses explicit DTSTART from string
- Respects DTSTART timezone or uses schedule.timezone

### Implementation Code Structure

```python
def _resolve_rrule(self, schedule: Schedule) -> Optional[datetime]:
    """Resolve RRULE schedule (iCal recurrence rule).
    
    Uses python-dateutil.rrule which is RFC 5545 compliant.
    Already available in requirements.txt, no new dependency needed.
    """
    try:
        from dateutil.rrule import rrulestr
        
        # Get timezone
        tz = pytz.timezone(schedule.timezone or "UTC")
        now_tz = datetime.now(tz)
        
        # Determine DTSTART
        dtstart = self._get_rrule_dtstart(schedule, tz)
        
        # Parse RRULE string from schedule_spec
        rrule_spec = schedule.schedule_spec.strip()
        
        # If RRULE doesn't include DTSTART, prepend it
        if "DTSTART" not in rrule_spec.upper():
            # Format DTSTART in iCal format
            dtstart_str = dtstart.strftime("%Y%m%dT%H%M%S")
            if dtstart.tzinfo:
                dtstart_str += dtstart.strftime("%z")
            else:
                dtstart_str += "Z"
            rrule_spec = f"DTSTART:{dtstart_str}\nRRULE:{rrule_spec}"
        
        # Parse RRULE string using dateutil.rrule
        rule = rrulestr(rrule_spec, dtstart=dtstart)
        
        # Get next occurrence after last_run_at or now
        after_time = schedule.last_run_at or now_tz
        if after_time.tzinfo is None:
            after_time = pytz.UTC.localize(after_time)
        after_time = after_time.astimezone(tz)
        
        # Find next occurrence using rule.after()
        next_occurrence = rule.after(after_time)
        
        if next_occurrence is None:
            # RRULE exhausted (COUNT reached or UNTIL passed)
            logger.info(f"RRULE schedule {schedule.id} has no more occurrences")
            return None
        
        # Convert to UTC for storage
        next_occurrence_utc = next_occurrence.astimezone(pytz.UTC).replace(tzinfo=None)
        
        return next_occurrence_utc
        
    except Exception as e:
        logger.error(f"Error parsing RRULE schedule {schedule.id}: {str(e)}")
        return None

def _get_rrule_dtstart(self, schedule: Schedule, tz: pytz.timezone) -> datetime:
    """Get DTSTART for RRULE (from schedule or inferred)."""
    # If schedule_spec has DTSTART, extract it
    # Otherwise use schedule.created_at or current time
    dtstart = schedule.created_at or datetime.utcnow()
    
    # Make timezone-aware
    if dtstart.tzinfo is None:
        dtstart = pytz.UTC.localize(dtstart)
    
    # Convert to schedule timezone
    dtstart = dtstart.astimezone(tz)
    
    return dtstart
```

### Test Cases

#### Basic RRULE Patterns
```python
# Daily
"FREQ=DAILY;INTERVAL=1"

# Weekly on specific days
"FREQ=WEEKLY;BYDAY=MO,WE,FR"

# Monthly on first day
"FREQ=MONTHLY;BYMONTHDAY=1"

# Every 2 weeks on Monday
"FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"

# First Monday of month
"FREQ=MONTHLY;BYDAY=MO;BYMONTHDAY=1,2,3,4,5,6,7"
```

#### Advanced Patterns
```python
# With COUNT limit
"FREQ=DAILY;INTERVAL=1;COUNT=10"

# With UNTIL limit
"FREQ=DAILY;INTERVAL=1;UNTIL=20241231T235959Z"

# Complex: Last Monday of each month
"FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1"

# Yearly on specific date
"FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25"
```

## Implementation Checklist

### Step 1: Core Implementation
- [ ] Import `dateutil.rrule` in `scheduler_service.py`
- [ ] Implement `_resolve_rrule()` method
- [ ] Implement `_get_rrule_dtstart()` helper
- [ ] Add timezone handling
- [ ] Convert results to UTC for storage

### Step 2: Edge Cases & Error Handling
- [ ] Handle missing DTSTART
- [ ] Handle expired RRULE (UNTIL passed)
- [ ] Handle exhausted COUNT
- [ ] Handle invalid RRULE format
- [ ] Handle timezone conversion errors

### Step 3: Testing
- [ ] Update `test_resolve_rrule_stub()` to test real implementation
- [ ] Add test for daily RRULE
- [ ] Add test for weekly RRULE with BYDAY
- [ ] Add test for monthly RRULE
- [ ] Add test for COUNT limit
- [ ] Add test for UNTIL limit
- [ ] Add test for timezone handling
- [ ] Add test for invalid RRULE
- [ ] Add test for expired RRULE

### Step 4: Integration
- [ ] Test with scheduler_tick task
- [ ] Verify job creation from RRULE schedule
- [ ] Verify next_run_at updates correctly
- [ ] Test concurrent scheduler instances

### Step 5: Documentation
- [ ] Update IMPLEMENTATION_PLAN.md (mark Iteration 7 as complete)
- [ ] Update QUEUE.md with RRULE examples
- [ ] Add RRULE format documentation
- [ ] Update API documentation

## Dependencies

### Required Library: `python-dateutil`
- ✅ **Already installed**: `python-dateutil>=2.8.0` (in `requirements.txt`)
- **Module to use**: `dateutil.rrule`
- **Key functions**:
  - `rrulestr()` - Parse RRULE string from iCal format
  - `rrule()` - Create RRULE programmatically (optional)
  
**Import statement:**
```python
from dateutil.rrule import rrulestr
```

**Why `python-dateutil`?**
- ✅ Already in project dependencies (no new dependency needed)
- ✅ Full RFC 5545 compliance (iCal RRULE standard)
- ✅ Well-maintained and widely used
- ✅ Handles all RRULE components (FREQ, COUNT, UNTIL, BYDAY, etc.)
- ✅ Timezone-aware calculations
- ✅ Efficient next occurrence computation

### Alternative Libraries (Not Needed)
- **`rrule`** (standalone) - Similar functionality but requires new dependency
- **`icalendar`** - Full iCal parser (overkill for our needs)
- **`django-pg-rrule`** - Django-specific, not applicable

**Conclusion**: Use `python-dateutil.rrule` - it's already available and sufficient for our needs.

## RRULE Format Examples

### Supported RRULE Components

| Component | Example | Description |
|-----------|---------|-------------|
| FREQ | `FREQ=DAILY` | Frequency: DAILY, WEEKLY, MONTHLY, YEARLY |
| INTERVAL | `INTERVAL=2` | Every N intervals (e.g., every 2 days) |
| COUNT | `COUNT=10` | Stop after N occurrences |
| UNTIL | `UNTIL=20241231T235959Z` | Stop before this date |
| BYDAY | `BYDAY=MO,WE,FR` | On these weekdays |
| BYMONTHDAY | `BYMONTHDAY=1,15` | On these days of month |
| BYMONTH | `BYMONTH=1,6,12` | In these months |
| BYSETPOS | `BYSETPOS=-1` | Nth occurrence (negative = from end) |

### Common Patterns

```python
# Daily at same time
"FREQ=DAILY;INTERVAL=1"

# Every weekday (Monday-Friday)
"FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"

# Twice weekly (Monday and Thursday)
"FREQ=WEEKLY;BYDAY=MO,TH"

# First of every month
"FREQ=MONTHLY;BYMONTHDAY=1"

# Last Friday of month
"FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1"

# Every 15th of month
"FREQ=MONTHLY;BYMONTHDAY=15"

# Quarterly (first day of every 3 months)
"FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=1"

# Yearly on Christmas
"FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25"

# Every 2 weeks on Monday (biweekly)
"FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"
```

## Error Handling

### Invalid RRULE Format
- Log error with schedule ID
- Return `None` to disable schedule
- Don't crash scheduler tick

### Expired RRULE (UNTIL passed)
- Return `None` to disable schedule
- Log informational message

### Exhausted COUNT
- Return `None` after last occurrence
- Log informational message

### Missing DTSTART
- Use `schedule.created_at` if available
- Otherwise use current time
- Log warning if inferred

## Testing Strategy

### Unit Tests
1. **Basic patterns**: Daily, weekly, monthly
2. **BYDAY patterns**: Specific weekdays
3. **COUNT limits**: Verify stops after N occurrences
4. **UNTIL limits**: Verify stops at date
5. **Timezone handling**: Convert correctly
6. **Edge cases**: Invalid format, expired rule

### Integration Tests
1. Create RRULE schedule via API
2. Verify scheduler_tick creates job
3. Verify next_run_at updates
4. Verify schedule disables when exhausted

### Performance Tests
- Test with large COUNT values
- Test with complex BYDAY combinations
- Measure RRULE parsing time

## Migration Notes

### Existing Data
- Existing RRULE schedules will start working once implemented
- No database migration needed
- Schedules with invalid RRULE will be disabled

### Backward Compatibility
- Existing one-shot and cron schedules unaffected
- RRULE implementation is additive

## Success Criteria

✅ **Phase 1 Complete When:**
- Basic RRULE parsing works (DAILY, WEEKLY, MONTHLY)
- Timezone handling correct
- Next occurrence computed correctly
- Unit tests pass

✅ **Phase 2 Complete When:**
- COUNT and UNTIL limits work
- Complex BY rules work
- Error handling comprehensive
- Integration tests pass

✅ **Phase 3 Complete When:**
- All test cases pass
- Performance acceptable
- Documentation updated
- No regressions in existing functionality

## Estimated Effort

- **Phase 1**: 2-3 hours (core implementation)
- **Phase 2**: 2-3 hours (advanced features)
- **Phase 3**: 2-3 hours (testing & validation)
- **Phase 4**: 1 hour (documentation)

**Total**: ~8-10 hours

## Next Steps

1. Review this plan
2. Implement Phase 1 (core RRULE parsing)
3. Test with common patterns
4. Iterate on Phase 2 (advanced features)
5. Complete testing and documentation

---

## Appendix: RRULE Reference

### FREQ Values
- `DAILY`: Daily recurrence
- `WEEKLY`: Weekly recurrence
- `MONTHLY`: Monthly recurrence
- `YEARLY`: Yearly recurrence

### BYDAY Values
- `MO`, `TU`, `WE`, `TH`, `FR`, `SA`, `SU`
- Can combine: `BYDAY=MO,WE,FR`
- Can use ordinals: `1MO` (first Monday), `-1FR` (last Friday)

### BYMONTH Values
- 1-12 (January-December)
- Can combine: `BYMONTH=1,6,12`

### RRULE vs Cron Comparison

| Use Case | Cron | RRULE |
|----------|------|-------|
| Every day at 9 AM | `0 9 * * *` | `FREQ=DAILY;BYHOUR=9;BYMINUTE=0` |
| Every Monday | `0 9 * * 1` | `FREQ=WEEKLY;BYDAY=MO` |
| First of month | `0 9 1 * *` | `FREQ=MONTHLY;BYMONTHDAY=1` |
| Last Friday of month | ❌ Complex | `FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1` |
| Every 2 weeks | ❌ Not possible | `FREQ=WEEKLY;INTERVAL=2` |

**Conclusion**: RRULE is more powerful for complex recurring patterns.

