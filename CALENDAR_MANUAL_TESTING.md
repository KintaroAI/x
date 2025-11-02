# Calendar Manual Testing Checklist

This document provides a manual testing checklist for the calendar feature.

## Prerequisites

1. Start the development environment:
   ```bash
   make dev
   ```

2. Ensure database is initialized:
   ```bash
   make init-db
   ```

3. Verify services are running:
   ```bash
   docker compose ps
   ```

## Test Cases

### 1. Basic Calendar View

- [ ] Navigate to `/calendar` from navigation menu
- [ ] Verify calendar page loads without errors
- [ ] Verify week view displays (7 days × 48 time slots)
- [ ] Verify time labels on left column (00:00 to 23:30)
- [ ] Verify day headers show correct dates

### 2. Week Navigation

- [ ] Click "Prev" button - verify week shifts to previous week
- [ ] Click "Next" button - verify week shifts to next week
- [ ] Click "Today" button - verify week returns to current week
- [ ] Verify week range display updates correctly
- [ ] Verify URL parameter `week_start` updates when navigating

### 3. Schedule Types - One Shot

- [ ] Create a post with one-shot schedule in current week
- [ ] Verify post appears as block on calendar at scheduled time
- [ ] Verify block is clickable and navigates to post view
- [ ] Verify block shows post text preview
- [ ] Verify block shows scheduled time

- [ ] Create a post with one-shot schedule in future week
- [ ] Navigate to that week
- [ ] Verify post appears in correct week

- [ ] Create a post with one-shot schedule in past
- [ ] Verify post does not appear in calendar

### 4. Schedule Types - Cron

- [ ] Create a post with daily cron schedule (e.g., `0 9 * * *`)
- [ ] Verify post appears as multiple blocks (one per day) in week
- [ ] Verify all blocks are at correct time (9 AM)
- [ ] Verify all blocks are clickable

- [ ] Create a post with hourly cron schedule
- [ ] Verify multiple occurrences appear (should be capped at 300)
- [ ] Verify occurrences are distributed across days correctly

- [ ] Create a post with cron schedule outside visible hours
- [ ] Verify post appears at grid boundaries if scheduled outside 00:00-23:59

### 5. Schedule Types - RRULE

- [ ] Create a post with daily RRULE schedule (e.g., `FREQ=DAILY;BYHOUR=10;BYMINUTE=30`)
- [ ] Verify post appears as multiple blocks (one per day) in week
- [ ] Verify all blocks are at correct time (10:30 AM)

- [ ] Create a post with weekly RRULE schedule
- [ ] Verify post appears once per week at scheduled time

- [ ] Create a post with RRULE that has COUNT limit
- [ ] Verify occurrences respect COUNT limit

- [ ] Create a post with RRULE that would exceed 300 occurrences
- [ ] Verify occurrences are capped at 300

### 6. Overlapping Posts

- [ ] Create multiple posts scheduled at the same time (within 30 minutes)
- [ ] Verify posts appear stacked (offset vertically)
- [ ] Verify stack order is deterministic (doesn't change on reload)
- [ ] Verify each overlapping block is clickable
- [ ] Verify all blocks are visible (not completely hidden)

- [ ] Create 3+ posts at same time
- [ ] Verify all 3 appear with different stack_index values
- [ ] Verify blocks are visually distinct

### 7. Locale Support

- [ ] Navigate to calendar with `locale=sunday` parameter
- [ ] Verify week starts on Sunday
- [ ] Verify day headers show correct order (Sun-Sat)

- [ ] Navigate to calendar with `locale=monday` parameter
- [ ] Verify week starts on Monday
- [ ] Verify day headers show correct order (Mon-Sun)

- [ ] Test navigation preserves locale parameter

### 8. Timezone Handling

- [ ] Navigate to calendar with different timezone (e.g., `timezone=America/Chicago`)
- [ ] Verify times are displayed in correct timezone
- [ ] Verify week boundaries calculated correctly for timezone

- [ ] Test with timezone that has DST (e.g., America/Chicago)
- [ ] Navigate to week that includes spring forward (typically March)
- [ ] Verify grid handles 23-hour day correctly
- [ ] Verify post blocks align correctly during DST transition

- [ ] Navigate to week that includes fall back (typically November)
- [ ] Verify grid handles 25-hour day correctly
- [ ] Verify post blocks align correctly during DST transition

### 9. Post Block Interactions

- [ ] Click on a post block
- [ ] Verify navigation to `/view-post/{post_id}`
- [ ] Verify correct post is displayed

- [ ] Hover over a post block
- [ ] Verify tooltip shows full post text (if truncated)
- [ ] Verify tooltip shows post ID and scheduled time

- [ ] Verify block styling (colors, borders, hover effects)

### 10. Edge Cases

- [ ] Create post scheduled at 00:00 (midnight)
- [ ] Verify block appears at top of calendar grid

- [ ] Create post scheduled at 23:59
- [ ] Verify block appears at bottom of calendar grid

- [ ] Create post with very long text (>50 characters)
- [ ] Verify text is truncated in preview
- [ ] Verify full text shown on hover

- [ ] Create post spanning multiple 30-minute slots (duration > 30 min)
- [ ] Verify block height adjusts to span multiple slots

- [ ] Create disabled schedule
- [ ] Verify disabled schedule's posts do not appear in calendar

- [ ] Create deleted post with schedule
- [ ] Verify deleted post's schedule does not appear in calendar

### 11. Performance

- [ ] Create multiple schedules (10+ posts with different schedules)
- [ ] Verify calendar loads within reasonable time (< 2 seconds)
- [ ] Verify no console errors
- [ ] Verify calendar is scrollable smoothly

- [ ] Create cron schedule that generates 300+ occurrences
- [ ] Verify calendar handles large number of occurrences
- [ ] Verify occurrences are capped at 300 per schedule

### 12. Responsive Design

- [ ] Resize browser window to mobile size (< 768px)
- [ ] Verify calendar is still usable (may need horizontal scroll)
- [ ] Verify post blocks are still clickable
- [ ] Verify time labels remain visible

- [ ] Resize browser window to tablet size (768px - 1024px)
- [ ] Verify calendar layout adapts appropriately

### 13. Error Handling

- [ ] Navigate to calendar with invalid `week_start` parameter
- [ ] Verify calendar still loads (uses current week as fallback)
- [ ] Verify no error messages displayed

- [ ] Navigate to calendar with invalid `timezone` parameter
- [ ] Verify calendar uses default timezone as fallback

- [ ] Disconnect database temporarily
- [ ] Verify calendar handles error gracefully
- [ ] Verify user-friendly error message (if implemented)

## Expected Results

### Successful Calendar Display

- Calendar grid shows 7 days × 48 time slots (30-minute increments)
- All scheduled posts appear as colored blocks
- Post blocks positioned at correct time slots
- Post blocks clickable and navigate to post view
- Week navigation works correctly
- Locale and timezone parameters respected

### Known Limitations

- Recurring schedules capped at 300 occurrences per schedule per week
- Overlapping posts stacked vertically with offset
- Text truncated at 50 characters with "..." suffix
- Minimum block height of 20px for readability

## Troubleshooting

If calendar doesn't load:
1. Check browser console for JavaScript errors
2. Check API endpoint `/api/calendar/week` returns valid JSON
3. Verify database connection
4. Verify services are running (`docker compose ps`)

If posts don't appear:
1. Verify schedules are enabled (`enabled=True`)
2. Verify posts are not deleted (`deleted=False`)
3. Verify schedules have `next_run_at` or recurring pattern
4. Verify you're viewing the correct week

If times are incorrect:
1. Verify timezone parameter is correct
2. Check if DST transition might affect display
3. Verify schedule timezone is set correctly

## Test Data Setup

### Quick Test Data Script

You can use this to create test data:

```python
# Create test posts with different schedule types
# Run in: docker compose exec api python -c "..."
```

### Sample Schedules to Test

1. **One-shot**: Post scheduled for tomorrow at 2 PM
2. **Cron daily**: Post scheduled daily at 9 AM (`0 9 * * *`)
3. **Cron hourly**: Post scheduled every hour (`0 * * * *`)
4. **RRULE daily**: `FREQ=DAILY;BYHOUR=10;BYMINUTE=30`
5. **RRULE weekly**: `FREQ=WEEKLY;BYDAY=MO;BYHOUR=14`
6. **Multiple overlapping**: 3 posts at same time (e.g., 12:00 PM)

## Reporting Issues

When reporting issues, include:
1. Browser and version
2. Steps to reproduce
3. Expected vs actual behavior
4. Console errors (if any)
5. Network requests to `/api/calendar/week`
6. Screenshot (if applicable)

