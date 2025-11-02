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

## Production Considerations

### Critical Design Decisions

1. **DTSTART Smart Snapping** (Prevents Drift)
   - Problem: Using `created_at` directly can create schedules on odd minute boundaries (e.g., 14:23:17)
   - Solution: If BYHOUR/BYMINUTE/BYSECOND present in RRULE, snap DTSTART to that wall time on or after `now`
   - Otherwise: Use `schedule.created_at` as-is
   - Prevents schedules from "drifting" to weird times

2. **`after()` Inclusivity Semantics** (Avoid Off-by-One Bugs)
   - Decide once: Use `rule.after(time, inc=False)` - default behavior
     - `inc=False`: Skip occurrence if it equals the reference time (safe for "next occurrence")
     - `inc=True`: Include occurrence if it equals reference time (may cause duplicate runs)
   - Document this choice explicitly to avoid confusion

3. **COUNT Semantics Depend on DTSTART**
   - COUNT counts occurrences from DTSTART
   - If DTSTART is wrong, COUNT may exhaust prematurely
   - With smart snapping (point 1), this becomes predictable
   - Add tests for COUNT with both explicit and inferred DTSTART

4. **DST & Nonexistent Times**
   - Behavior: Events stay at **local wall time** (e.g., "09:00 America/Chicago" stays 9am year-round)
   - `dateutil` handles this automatically
   - Document this behavior clearly
   - Add tests around DST boundaries (spring forward, fall back)

5. **Performance: Parse-Once Caching**
   - Problem: Parsing RRULE on every scheduler tick adds latency
   - Solution: In-process cache keyed by `(schedule_id, rrule_hash, dtstart)`
   - Cache compiled `rrule`/`rruleset` objects
   - Invalidate when `schedule_spec` changes or DTSTART changes
   - Keeps tick latency stable with many schedules

6. **Validation & Guardrails** (Security)
   - Before parsing: Whitelist allowed RRULE components (FREQ, BYxxx, COUNT, UNTIL, INTERVAL)
   - Size limits: Prevent pathological inputs (e.g., massive BYDAY lists)
   - Return structured 400 errors via API instead of silently disabling
   - Log validation failures for debugging

7. **RDATE/EXDATE Support** (Future Feature)
   - For real-world calendars (holidays, blackouts)
   - Use `rruleset()` instead of `rrule()` when RDATE/EXDATE present
   - Allows `exdate()`/`rdate()` alongside main rule
   - Enables "pause specific dates" UI feature later

8. **Storage Convention** (Prevent Regressions)
   - Convert to UTC: `dt.astimezone(pytz.UTC)`
   - Store as naive: `.replace(tzinfo=None)` (consistent with existing codebase)
   - Document this convention so other contributors don't accidentally store timezone-aware datetimes
   - Prevents double-conversion bugs

9. **Examples: Prefer BYSETPOS Canonical Forms**
   - Use canonical forms for clarity:
     - First Monday: `FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1`
     - Last Friday: `FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1`
   - More readable than complex BYMONTHDAY calculations

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
- **DTSTART smart inference**: 
  - If BYHOUR/BYMINUTE/BYSECOND present, snap DTSTART to that wall time on or after `now`
  - Otherwise, use `schedule.created_at` or current time
- Use `pytz.timezone()` for timezone-aware calculations (consistent with existing codebase)
- **Clarify `after()` inclusivity**: Document and decide whether `inc=True` or `inc=False` (default False - skips "right now" runs)
- Handle missing/explicit DTSTART gracefully
- Return `None` if RRULE has expired (UNTIL passed, COUNT exhausted)
- **Performance**: Add caching for compiled RRULE objects (keyed by `schedule_id`, invalidate on `schedule_spec` change)
- **Storage convention**: Store as naive UTC datetime (`.replace(tzinfo=None)` after conversion) - document this convention

### Phase 2: Advanced RRULE Features
**Goal**: Support COUNT, UNTIL, BYDAY, BYMONTH, RDATE/EXDATE, etc.

**Tasks:**
1. Support COUNT limit (stop after N occurrences)
2. Support UNTIL limit (stop before date)
3. Handle complex BY rules (BYDAY, BYMONTHDAY, BYMONTH, BYYEARDAY, BYWEEKNO, BYSETPOS)
4. Support RDATE/EXDATE for inclusion/exclusion dates (holidays, blackouts)
5. Validate RRULE format and provide helpful error messages
6. Handle edge cases (leap years, invalid dates, DST transitions)
7. **DTSTART smart snapping**: If BYHOUR/BYMINUTE/BYSECOND present, snap DTSTART to that wall time

### Phase 3: Testing & Validation
**Goal**: Comprehensive test coverage

**Tasks:**
1. Unit tests for common RRULE patterns (including BYSETPOS canonical forms)
2. Integration tests with scheduler tick
3. Edge case tests:
   - Invalid RRULE format
   - Expired rules (UNTIL passed, COUNT exhausted)
   - Timezone handling (DST transitions, nonexistent times)
   - `after()` inclusivity semantics (inc=True vs inc=False)
   - COUNT with explicit vs inferred DTSTART
4. RDATE/EXDATE behavior and precedence tests
5. Concurrency tests (verify no duplicate scheduling under lock contention)
6. Performance tests (large COUNT values, caching effectiveness)

### Phase 4: Documentation & API Updates
**Goal**: Update documentation and API to support RRULE

**Tasks:**
1. Update API documentation for RRULE format
2. Update IMPLEMENTATION_PLAN.md status
3. Update QUEUE.md with RRULE examples (prefer BYSETPOS canonical forms)
4. Add RRULE validation in API endpoints:
   - Whitelist allowed RRULE components (FREQ, BYxxx, COUNT, UNTIL, INTERVAL)
   - Size limits to prevent pathological inputs
   - Return structured 400 errors instead of silently disabling
5. Document timezone storage convention (naive UTC)
6. Document DST behavior (events stay at local wall time)

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
# Cache for compiled RRULE objects (keyed by schedule_id)
_rrule_cache = {}  # {(schedule_id, rrule_hash): (rrule_obj, dtstart)}

def _resolve_rrule(self, schedule: Schedule) -> Optional[datetime]:
    """Resolve RRULE schedule (iCal recurrence rule).
    
    Uses python-dateutil.rrule which is RFC 5545 compliant.
    Already available in requirements.txt, no new dependency needed.
    
    Design decisions:
    - Uses after(time, inc=False) to skip occurrences at exact reference time
    - Stores as naive UTC datetime (consistent with existing codebase)
    - Caches compiled RRULE objects for performance
    """
    try:
        from dateutil.rrule import rrulestr
        import hashlib
        
        # Validate RRULE format before parsing
        if not self._validate_rrule(schedule.schedule_spec):
            logger.error(f"Invalid RRULE format for schedule {schedule.id}")
            return None
        
        # Get timezone (consistent with existing codebase using pytz)
        tz = pytz.timezone(schedule.timezone or "UTC")
        now_tz = datetime.now(tz)
        
        # Determine DTSTART (with smart snapping)
        dtstart = self._get_rrule_dtstart(schedule, tz, schedule.schedule_spec)
        
        # Check cache for compiled RRULE
        rrule_hash = hashlib.md5(schedule.schedule_spec.encode()).hexdigest()
        cache_key = (schedule.id, rrule_hash)
        
        if cache_key in _rrule_cache:
            cached_rule, cached_dtstart = _rrule_cache[cache_key]
            # Reuse if DTSTART matches
            if cached_dtstart == dtstart:
                rule = cached_rule
            else:
                # DTSTART changed, recompile
                rule = self._parse_rrule(schedule.schedule_spec, dtstart)
                _rrule_cache[cache_key] = (rule, dtstart)
        else:
            # Parse and cache
            rule = self._parse_rrule(schedule.schedule_spec, dtstart)
            _rrule_cache[cache_key] = (rule, dtstart)
            # Limit cache size (simple LRU)
            if len(_rrule_cache) > 1000:
                _rrule_cache.pop(next(iter(_rrule_cache)))
        
        # Get next occurrence after last_run_at or now
        after_time = schedule.last_run_at or now_tz
        if after_time.tzinfo is None:
            # Assume naive datetime is UTC (consistent with storage convention)
            after_time = pytz.UTC.localize(after_time)
        after_time = after_time.astimezone(tz)
        
        # Find next occurrence using rule.after(inc=False)
        # inc=False: Skip occurrence if it equals reference time (safe for "next occurrence")
        next_occurrence = rule.after(after_time, inc=False)
        
        if next_occurrence is None:
            # RRULE exhausted (COUNT reached or UNTIL passed)
            logger.info(f"RRULE schedule {schedule.id} has no more occurrences")
            return None
        
        # Convert to UTC for storage
        # Storage convention: Store as naive UTC datetime (consistent with existing codebase)
        next_occurrence_utc = next_occurrence.astimezone(pytz.UTC).replace(tzinfo=None)
        
        return next_occurrence_utc
        
    except Exception as e:
        logger.error(f"Error parsing RRULE schedule {schedule.id}: {str(e)}")
        return None

def _parse_rrule(self, rrule_spec: str, dtstart: datetime) -> 'rrule':
    """Parse RRULE string into rrule object."""
    from dateutil.rrule import rrulestr
    
    # Normalize RRULE spec (preserve case for values like UNTIL timestamps)
    rrule_spec = rrule_spec.strip()
    
    # If RRULE doesn't include DTSTART, prepend it
    if "DTSTART" not in rrule_spec.upper():
        # Format DTSTART in iCal format (YYYYMMDDTHHMMSSZ or with offset)
        if dtstart.tzinfo == pytz.UTC or dtstart.tzinfo is None:
            dtstart_str = dtstart.strftime("%Y%m%dT%H%M%S") + "Z"
        else:
            # Include timezone offset
            dtstart_str = dtstart.strftime("%Y%m%dT%H%M%S%z")
        rrule_spec = f"DTSTART:{dtstart_str}\nRRULE:{rrule_spec}"
    
    # Parse RRULE string using dateutil.rrule
    return rrulestr(rrule_spec, dtstart=dtstart)

def _get_rrule_dtstart(self, schedule: Schedule, tz: pytz.timezone, rrule_spec: str) -> datetime:
    """Get DTSTART for RRULE with smart snapping.
    
    If BYHOUR/BYMINUTE/BYSECOND present in RRULE, snap DTSTART to that wall time.
    Otherwise use schedule.created_at or current time.
    """
    import re
    
    # Extract time constraints from RRULE
    has_byhour = re.search(r'BYHOUR=(\d+)', rrule_spec.upper())
    has_byminute = re.search(r'BYMINUTE=(\d+)', rrule_spec.upper())
    has_bysecond = re.search(r'BYSECOND=(\d+)', rrule_spec.upper())
    
    # Base DTSTART from schedule or current time
    base_dtstart = schedule.created_at or datetime.utcnow()
    if base_dtstart.tzinfo is None:
        base_dtstart = pytz.UTC.localize(base_dtstart)
    base_dtstart = base_dtstart.astimezone(tz)
    
    # If time constraints present, snap to that wall time
    if has_byhour or has_byminute or has_bysecond:
        # Extract desired time components
        hour = int(has_byhour.group(1)) if has_byhour else base_dtstart.hour
        minute = int(has_byminute.group(1)) if has_byminute else base_dtstart.minute
        second = int(has_bysecond.group(1)) if has_bysecond else 0
        
        # Snap to wall time on or after now
        now_tz = datetime.now(tz)
        dtstart = tz.localize(datetime(
            base_dtstart.year, base_dtstart.month, base_dtstart.day,
            hour, minute, second
        ))
        
        # If snapped time is in past, move to next occurrence
        if dtstart < now_tz:
            # For daily/weekly patterns, advance by appropriate interval
            # This is a simplification; actual pattern would need full RRULE parse
            from dateutil.relativedelta import relativedelta
            if 'FREQ=DAILY' in rrule_spec.upper():
                dtstart += relativedelta(days=1)
            elif 'FREQ=WEEKLY' in rrule_spec.upper():
                dtstart += relativedelta(weeks=1)
            # For other frequencies, just use tomorrow as fallback
            else:
                dtstart += relativedelta(days=1)
        
        return dtstart
    else:
        # No time constraints, use base DTSTART as-is
        return base_dtstart

def _validate_rrule(self, rrule_spec: str) -> bool:
    """Validate RRULE format with whitelist and size limits."""
    # Whitelist allowed RRULE components
    ALLOWED_COMPONENTS = {
        'FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'BYMONTHDAY',
        'BYMONTH', 'BYYEARDAY', 'BYWEEKNO', 'BYSETPOS', 'BYHOUR',
        'BYMINUTE', 'BYSECOND', 'DTSTART', 'RRULE'
    }
    
    # Size limits
    MAX_RRULE_LENGTH = 10000  # Prevent pathological inputs
    
    if len(rrule_spec) > MAX_RRULE_LENGTH:
        return False
    
    # Extract component names from RRULE
    import re
    components = re.findall(r'([A-Z]+)=', rrule_spec.upper())
    
    # Check all components are whitelisted
    for component in components:
        if component not in ALLOWED_COMPONENTS:
            return False
    
    return True
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

### Common Patterns (Canonical Forms Preferred)

```python
# Daily at same time
"FREQ=DAILY;INTERVAL=1"

# Every weekday (Monday-Friday)
"FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"

# Twice weekly (Monday and Thursday)
"FREQ=WEEKLY;BYDAY=MO,TH"

# First of every month
"FREQ=MONTHLY;BYMONTHDAY=1"

# First Monday of month (canonical BYSETPOS form)
"FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1"

# Last Friday of month (canonical BYSETPOS form)
"FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1"

# Every 15th of month
"FREQ=MONTHLY;BYMONTHDAY=15"

# Quarterly (first day of every 3 months)
"FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=1"

# Yearly on Christmas
"FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25"

# Every 2 weeks on Monday (biweekly)
"FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"

# Hourly (for completeness)
"FREQ=HOURLY;INTERVAL=1"

# Minutely (for completeness)
"FREQ=MINUTELY;INTERVAL=5"

# Third Monday/Wednesday/Friday of month (canonical BYSETPOS)
"FREQ=MONTHLY;BYDAY=MO,WE,FR;BYSETPOS=3"
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

---

## Feedback Integration Summary

This plan has been enhanced based on production-grade feedback to ensure **"calendar-grade"** RRULE support:

### ✅ Incorporated Improvements

1. **DTSTART Smart Snapping** - Prevents drift by snapping to BYHOUR/BYMINUTE when present
2. **`after()` Inclusivity** - Explicitly documented `inc=False` to avoid off-by-one bugs
3. **COUNT Semantics** - Documented dependency on DTSTART, with tests planned
4. **DST Behavior** - Documented that events stay at local wall time
5. **Performance Caching** - Added in-process cache for compiled RRULE objects
6. **Validation & Guardrails** - Whitelist components, size limits, structured 400 errors
7. **Storage Convention** - Documented naive UTC storage to prevent regressions
8. **BYSETPOS Canonical Forms** - Examples updated to prefer canonical forms
9. **RDATE/EXDATE Support** - Added to Phase 2 for future feature
10. **Comprehensive Testing** - Added tests for DST, COUNT with DTSTART, cache invalidation, validation

### Design Decisions

- **Timezone**: Using `pytz` (consistent with existing codebase) - `zoneinfo` could be future enhancement
- **Caching**: Simple in-process cache with LRU eviction (can enhance with proper LRU later)
- **Validation**: Whitelist approach with size limits (prevents DoS while allowing legitimate RRULEs)
- **Error Handling**: Return `None` to disable schedule (consistent with existing behavior)

### Next Steps

1. Implement Phase 1 with all production considerations
2. Add comprehensive test suite covering all edge cases
3. Monitor performance and cache hit rates in production
4. Consider RDATE/EXDATE support based on user needs

