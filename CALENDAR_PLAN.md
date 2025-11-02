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
- **Input:** Week start date (optional, defaults to current week start)
- **Output:** List of scheduled posts with occurrences in the week
- **Logic:**
  1. Determine week boundaries (Sunday-Saturday or Monday-Sunday)
  2. Query all enabled schedules with `next_run_at` that could fall within the week
  3. For each schedule:
     - **one_shot**: If `next_run_at` is within the week, include it
     - **cron**: Generate all occurrences within the week using croniter
     - **rrule**: Generate all occurrences within the week using dateutil.rrule
  4. Return list of occurrences with: `post_id`, `post_text` (preview), `scheduled_time`, `schedule_id`, `schedule_kind`

**Key considerations:**
- Need to generate occurrences for recurring schedules, not just `next_run_at`
- Handle timezones correctly (convert to display timezone)
- Efficient generation (limit to week boundaries)
- Cache or optimize for performance if needed

### Phase 2: Backend - Route Handler

**File: `src/api/routes.py`**

Add function `calendar_page()`:
- Render calendar template
- Pass week start date to template
- Optionally pass timezone information

**File: `src/main.py`**

Add route:
- `@app.get("/calendar", response_class=HTMLResponse)`

### Phase 3: Backend - Service Helper Functions

**File: `src/services/scheduler_service.py` or new `src/services/calendar_service.py`**

Add helper functions:
- `generate_week_occurrences(schedule, week_start, week_end, tz)`: Generate all occurrences for a schedule within a week
- `get_week_boundaries(date, tz)`: Calculate week start and end dates
- `format_occurrence_for_calendar(occurrence, post, schedule)`: Format occurrence data for frontend

**Considerations:**
- Use existing `ScheduleResolver` for cron/rrule parsing
- Generate occurrences efficiently (stop at week_end)
- Handle DST transitions correctly
- Limit generation to prevent infinite loops (e.g., max 100 occurrences per schedule)

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
- Block position: top = (minutes_from_midnight / 30) * slot_height
- Block height: duration (default 30 minutes) or until next post

**Considerations:**
- Handle posts that span multiple 30-minute slots
- Handle overlapping posts (stack or offset)
- Handle posts at exact boundaries
- Responsive adjustments for smaller screens

### Phase 6: API Endpoint for Weekly Data

**File: `src/api/posts.py`**

Add async function:
```python
async def get_weekly_schedule(week_start: Optional[str] = None, timezone: Optional[str] = None):
    """Get all scheduled posts for a week."""
```

**File: `src/main.py`**

Add route:
```python
@app.get("/api/calendar/week")
async def get_weekly_schedule(week_start: Optional[str] = None, timezone: Optional[str] = None):
    """Get weekly schedule data."""
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
  "timezone": "America/New_York",
  "occurrences": [
    {
      "post_id": 1,
      "post_text_preview": "This is a sample post...",
      "schedule_id": 5,
      "schedule_kind": "cron",
      "scheduled_time": "2024-01-01T09:00:00Z",
      "scheduled_time_local": "2024-01-01T04:00:00-05:00"
    }
  ]
}
```

### Calendar Grid Positioning

- **Time slots:** 48 slots per day (00:00, 00:30, 01:00, ..., 23:30)
- **Slot height:** Total visible height / 48
- **Block positioning:**
  - `top = (hours * 2 + minutes / 30) * slot_height`
  - `left = day_index * day_width + margin`
  - `height = max(30, slot_height)` (minimum readable height)
  - `width = day_width - margins`

### Handling Overlapping Posts

Options:
1. **Stack vertically:** Offset overlapping blocks
2. **Side-by-side:** Split day column if multiple posts at same time
3. **Z-index layering:** Show most recent on top

Initial implementation: **Simple stacking** with small vertical offset.

## Technical Considerations

1. **Performance:**
   - Cache week data if frequently accessed
   - Limit recurrence generation (e.g., max 100 occurrences per schedule)
   - Efficient database queries (index on `next_run_at`, `enabled`)

2. **Timezone Handling:**
   - Display all times in user's timezone (or default timezone)
   - Store and query in UTC, convert for display
   - Handle DST transitions correctly

3. **Edge Cases:**
   - Posts scheduled outside visible hours (00:00-23:59)
   - Recurring schedules with no occurrences in the week
   - Disabled schedules
   - Posts with very long text (truncate in preview)

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
   - Test occurrence generation for each schedule type
   - Test week boundary calculations
   - Test timezone conversions

2. **Integration tests:**
   - Test API endpoint with various schedule types
   - Test calendar rendering with sample data

3. **Manual testing:**
   - Test with one_shot, cron, and rrule schedules
   - Test week navigation
   - Test click-through to post view
   - Test with overlapping posts
   - Test responsive design

