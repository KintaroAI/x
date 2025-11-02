# Weekly Calendar View Implementation Plan

## Requirements

1. **Visual Design:**
   - Google Calendar-like interface
   - 7 days of the week as columns (Sunday through Saturday, or Monday through Sunday based on locale)
   - 30-minute grid as rows (48 rows per day: 24 hours × 2)
   - All scheduled posts shown as blocks on the grid
   - Blocks are clickable and lead to post view page

2. **Data Requirements:**
   - Show all posts that have scheduled occurrences in the selected week
   - Handle three schedule types:
     - **one_shot**: Single datetime occurrence
     - **cron**: Recurring schedule via cron expression
     - **rrule**: Recurring schedule via iCal RRULE

3. **Functionality:**
   - Week navigation (previous/next week)
   - Display posts as blocks positioned according to their scheduled time
   - Click on a block to navigate to `/view-post/{post_id}`
   - Handle overlapping posts (multiple posts at same time)

## Implementation Plan

### Phase 1: Backend - API Endpoint for Weekly Schedule Data

**File: `src/api/posts.py`**

Add function `get_weekly_schedule()`:
- **Input:** Week start date (optional, defaults to current week start), timezone (optional), locale (optional, 'sunday' or 'monday')
- **Output:** List of scheduled posts with occurrences in the week
- **Logic:**
  1. Determine week boundaries based on locale (Sunday-Saturday or Monday-Sunday)
  2. **Query all enabled schedules** (not just those with `next_run_at` in range):
     - Filter: `Schedule.enabled == True`
     - Join with `Post` to get post details
     - Use database indexes on `schedules(enabled, kind)` and `schedules(id)`
  3. For each schedule:
     - **one_shot**: If `next_run_at` is within the week, include it
     - **cron**: Generate all occurrences within the week using croniter with `after`/`before` windows
     - **rrule**: Generate all occurrences within the week using dateutil.rrule with `after`/`before` windows
  4. **Bound recurrence generation:**
     - Hard cap: ≤ 300 occurrences per schedule per request
     - Use `after(week_start, inc=False)` and stop at `week_end`
     - Pre-sort results server-side by `scheduled_time`
  5. Return list of occurrences with full occurrence metadata (see Data Structure below)

**Key considerations:**
- Generate occurrences for all recurring schedules, not just those with `next_run_at` in range
- Handle timezones correctly: store UTC in DB, convert with IANA TZ at render time
- Efficient generation with concrete bounds (300 occurrences max per schedule)
- Use database indexes for query performance

### Phase 2: Backend - Route Handler

**File: `src/api/routes.py`**

Add function `calendar_page()`:
- Render calendar template
- Pass week start date, timezone, and locale to template
- Default locale to 'monday' if not provided

**File: `src/main.py`**

Add route:
- `@app.get("/calendar", response_class=HTMLResponse)`

### Phase 3: Backend - Service Helper Functions

**File: `src/services/scheduler_service.py` or new `src/services/calendar_service.py`**

Add helper functions:
- `generate_week_occurrences(schedule, week_start, week_end, tz, max_occurrences=300)`: Generate all occurrences for a schedule within a week
  - **cron**: Use `croniter.after(week_start, inc=False)` and iterate until `week_end` or max_occurrences
  - **rrule**: Use `rrule.after(week_start, inc=False)` and iterate until `week_end` or max_occurrences
  - **one_shot**: Single check if `next_run_at` is within bounds
  - **Hard cap**: Stop after 300 occurrences per schedule to prevent unbounded expansion
- `get_week_boundaries(date, tz, locale='monday')`: Calculate week start and end dates based on locale
- `format_occurrence_for_calendar(occurrence, post, schedule, stack_index)`: Format occurrence data with stack_index for deterministic overlap handling

**Considerations:**
- Use existing `ScheduleResolver` for cron/rrule parsing
- Generate occurrences efficiently using `after`/`before` windows (stop at week_end)
- Handle DST transitions correctly: compute display slots from localized datetimes, not `minutes_from_midnight` math alone
- Limit generation: hard cap of 300 occurrences per schedule per request
- Calculate `stack_index` server-side using stable sort (by `created_at` then `post_id`) to prevent UI reshuffling

### Phase 4: Frontend - Calendar Template

**File: `templates/calendar.html`**

Structure:
- Header with week navigation (prev/next buttons, week range display)
- Calendar grid:
  - Header row with day names
  - Time column on left (30-minute increments)
  - 7 day columns
  - Each cell is a 30-minute slot
- Post blocks positioned absolutely within cells based on time
- Click handlers to navigate to post view

**Styling:**
- Use Tailwind CSS (already in base template)
- Google Calendar-like appearance:
  - Light borders between cells
  - Gray time labels on left
  - Colored post blocks with text preview
  - Hover effects on blocks
- Responsive design considerations

### Phase 5: Frontend - JavaScript for Calendar Rendering

**In `templates/calendar.html`:**

Add JavaScript functions:
- `loadWeekSchedule(weekStart)`: Fetch schedule data from API
- `renderCalendar(occurrences, weekStart)`: Render the calendar grid with post blocks
- `positionPostBlock(occurrence)`: Calculate CSS position for post block
- `navigateWeek(direction)`: Handle prev/next week navigation
- `calculateTimeSlotPosition(time)`: Convert datetime to grid position

**Key calculations:**
- Each day column: width = (100% - time column width) / 7
- Each 30-minute slot: height = (total height) / 48
- **DST-aware block positioning:**
  - Use localized datetime boundaries (not raw `minutes_from_midnight` math)
  - For 23/25-hour days during DST transitions, align blocks to actual local time slots
  - Calculate `top` from localized datetime: `(hours * 2 + minutes / 30) * slot_height`
- Block height: `max(duration_minutes / 30 * slot_height, 18-20px)` for minimum readable height
- Block width: `day_width - margins`
- **Use CSS transforms** for positioning to keep scroll smooth (not just `top`/`left`)

**Considerations:**
- Handle posts that span multiple 30-minute slots (use `duration_minutes` from API)
- Handle overlapping posts: use server-provided `stack_index` for deterministic vertical offset
- Handle posts at exact boundaries (DST transition hours)
- **Text truncation**: Show preview text with full text on hover
- **Minimum visual height**: 18-20px for blocks with text truncation
- Responsive adjustments for smaller screens

### Phase 6: API Endpoint for Weekly Data

**File: `src/api/posts.py`**

Add async function:
```python
async def get_weekly_schedule(
    week_start: Optional[str] = None, 
    timezone: Optional[str] = None,
    locale: Optional[str] = 'monday'
):
    """Get all scheduled posts for a week.
    
    Args:
        week_start: ISO date string (YYYY-MM-DD), defaults to current week start
        timezone: IANA timezone string (e.g., 'America/Chicago'), defaults to default_timezone
        locale: Week start day ('sunday' or 'monday'), defaults to 'monday'
    
    Returns:
        JSON with week metadata and occurrences array
    """
```

**File: `src/main.py`**

Add route:
```python
@app.get("/api/calendar/week")
async def get_weekly_schedule(
    week_start: Optional[str] = None, 
    timezone: Optional[str] = None,
    locale: Optional[str] = 'monday'
):
    """Get weekly schedule data.
    
    Includes locale in response so client doesn't need to infer week boundaries.
    """
```

### Phase 7: Navigation Integration

Update `templates/base.html`:
- Add "Calendar" link to navigation menu

## Implementation Details

### Data Structure for API Response

```json
{
  "week_start": "2024-01-01T00:00:00Z",
  "week_end": "2024-01-07T23:59:59Z",
  "timezone": "America/Chicago",
  "locale": "monday",
  "occurrences": [
    {
      "occurrence_id": "a1b2c3d4e5f6",
      "post_id": 1,
      "post_text_preview": "This is a sample post...",
      "schedule_id": 5,
      "schedule_kind": "cron",
      "source": "cron",
      "scheduled_time": "2024-01-01T09:00:00Z",
      "scheduled_time_local": "2024-01-01T04:00:00-05:00",
      "duration_minutes": 30,
      "status": "planned",
      "color_hint": "#3B82F6",
      "stack_index": 0
    }
  ]
}
```

**Field descriptions:**
- `occurrence_id`: Unique identifier (hash of `schedule_id + scheduled_time` in UTC)
- `post_id`: Post identifier
- `post_text_preview`: Truncated post text for display (e.g., first 50 chars)
- `schedule_id`: Schedule identifier
- `schedule_kind`: Schedule type ('one_shot', 'cron', 'rrule')
- `source`: Explicit schedule type (same as `schedule_kind`, kept for clarity)
- `scheduled_time`: UTC datetime (ISO 8601)
- `scheduled_time_local`: Localized datetime in response timezone (ISO 8601 with offset)
- `duration_minutes`: Duration of the post block (default: 30)
- `status`: Current status ('planned', 'paused', 'skipped', 'published')
- `color_hint`: Optional color for block rendering (hex format)
- `stack_index`: Server-calculated index for deterministic overlap stacking (stable sort by `created_at` then `post_id`)

### Calendar Grid Positioning

- **Time slots:** 48 slots per day (00:00, 00:30, 01:00, ..., 23:30)
- **Slot height:** Total visible height / 48
- **DST-aware block positioning:**
  - Calculate from localized datetime (not raw `minutes_from_midnight`)
  - Handle 23/25-hour days during DST transitions correctly
  - `top = (localized_hours * 2 + localized_minutes / 30) * slot_height`
  - Use CSS `transform: translate()` for smooth scrolling
- **Block dimensions:**
  - `left = day_index * day_width + margin`
  - `height = max(duration_minutes / 30 * slot_height, 20px)` (minimum 20px for readability)
  - `width = day_width - margins - (stack_index * overlap_offset)`
- **CSS positioning:**
  - Use CSS transforms (`transform: translateX() translateY()`) instead of `top`/`left` for performance
  - Apply `position: absolute` for blocks within day container

### Handling Overlapping Posts

**Implementation: Deterministic stacking with server-calculated `stack_index`**

- Server calculates `stack_index` using stable sort:
  - Sort by `schedule.created_at` (ascending)
  - Then by `post.id` (ascending)
- UI uses `stack_index` for vertical offset:
  - Each overlapping block offsets by `stack_index * 4px` (or similar small offset)
  - Blocks can slightly overlap horizontally to indicate stacking
  - Stable sorting prevents flicker on re-render
- Minimum visual separation: 2-4px between overlapping blocks

## Technical Considerations

1. **Performance:**
   - Cache week data if frequently accessed
   - **Hard cap recurrence generation: ≤ 300 occurrences per schedule per request**
   - **Efficient database queries:**
     - Query all enabled schedules: `Schedule.enabled == True`
     - Use database indexes:
       - `schedules(enabled, kind)` - Composite index for enabled schedule queries
       - `schedules(id)` - Primary key (already indexed)
       - `posts(id)` - Primary key (already indexed)
     - Join with `Post` table for post details
     - Pre-sort results server-side by `scheduled_time` to reduce client work

2. **Timezone Handling:**
   - **Storage:** Store all datetimes in UTC in database
   - **Display:** Convert with IANA timezone (e.g., `pytz.timezone('America/Chicago')`) at render time
   - **DST handling:**
     - Use localized datetime boundaries for grid calculations (not raw `minutes_from_midnight` math)
     - Handle 23/25-hour days during DST transitions correctly
     - Ensure grid aligns blocks to actual local time slots during transition
     - Test with `America/Chicago` timezone (known DST edge cases)

3. **Edge Cases:**
   - Posts scheduled outside visible hours (00:00-23:59) - show at grid boundaries
   - Recurring schedules with no occurrences in the week - exclude from results
   - Disabled schedules - excluded from query (`enabled == True`)
   - Posts with very long text - truncate in preview, show full on hover
   - Recurrence generation hitting 300-occurrence cap - log warning, include first 300
   - DST transitions creating 23/25-hour days - handle grid alignment correctly

4. **Future Enhancements (out of scope for MVP):**
   - Day view, month view
   - Drag-and-drop to reschedule
   - Filter by post status
   - Multiple calendars/views

## File Structure Summary

**New files:**
- `templates/calendar.html` - Calendar view template
- `src/services/calendar_service.py` (optional) - Calendar-specific helper functions

**Modified files:**
- `src/api/posts.py` - Add `get_weekly_schedule()` function
- `src/api/routes.py` - Add `calendar_page()` function
- `src/main.py` - Add calendar route and API endpoint
- `templates/base.html` - Add calendar link to navigation

**Dependencies:**
- Existing: `croniter`, `dateutil.rrule`, `pytz`
- No new dependencies required

## Testing Strategy

1. **Unit tests:**
   - Test occurrence generation for each schedule type (one_shot, cron, rrule)
   - Test week boundary calculations with different locales ('sunday', 'monday')
   - Test timezone conversions (UTC to various timezones)
   - **Test DST transition handling:**
     - Week that includes spring forward (DST begins) in `America/Chicago`
     - Week that includes fall back (DST ends) in `America/Chicago`
     - Verify grid alignment during 23/25-hour days
   - **Test recurrence limits:**
     - Cron with "every N minutes" that generates > 300 occurrences (should cap)
     - RRULE with COUNT vs UNTIL boundaries
     - Long-running RRULE capped by per-request limit (300 occurrences)

2. **Integration tests:**
   - Test API endpoint with various schedule types
   - Test API response includes all required fields (occurrence_id, duration_minutes, stack_index, etc.)
   - Test locale parameter ('sunday' vs 'monday')
   - Test calendar rendering with sample data
   - **Test database query efficiency:**
     - Verify enabled schedules query uses proper indexes
     - Verify no N+1 queries when joining with Post table

3. **Manual testing:**
   - Test with one_shot, cron, and rrule schedules
   - Test week navigation (previous/next week)
   - Test click-through to post view from calendar blocks
   - Test with overlapping posts (verify deterministic stacking)
   - Test responsive design
   - **Test edge cases:**
     - Posts scheduled at exact DST transition times
     - Multiple overlapping posts (3+ posts at same time)
     - Posts with very long text (verify truncation and hover)
     - Posts spanning multiple time slots (duration > 30 minutes)

