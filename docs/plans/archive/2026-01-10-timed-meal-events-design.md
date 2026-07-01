# Timed Meal Events Design

## Overview

Update the calendar sync feature to create separate timed events for each meal instead of all-day events.

## Event Structure

Each meal becomes its own calendar event:

| Meal | Time | Duration | Display |
|------|------|----------|---------|
| Breakfast | 8:00am | 30 min | Free |
| Lunch | 12:00pm | 30 min | Free |
| Snack | 3:00pm | 30 min | Free |
| Dinner | 7:30pm | 30 min | Free |

**Event title:** Just the recipe name (e.g., "Pancakes")

**Empty slots:** No event created if no recipe is linked for that meal.

**ICS properties:**
- `DTSTART`/`DTEND` with times (not all-day)
- `TRANSP: TRANSPARENT` (shows as free)
- Unique UID per meal: `2026-01-10-breakfast@kitchenos`

## Meal Plan Template Changes

Add a Snack section to each day in the weekly meal plan template:

```markdown
## Monday (Jan 13)

### Breakfast


### Lunch


### Snack


### Dinner


### Notes

```

**Migration:** Existing meal plans won't have the Snack section. The parser returns `None` for snack on those days (no event created).

## Parser Changes

`lib/meal_plan_parser.py` updates:

1. Add `'snack': None` to the meals dict
2. Include `snack` in the regex pattern loop
3. Return snack data in each day dict

No changes to recipe detection - still looks for `[[Recipe Name]]` links.

## ICS Generator Changes

`lib/ics_generator.py` restructure:

**New function:** `create_meal_event(day_date, meal_type, recipe_name)`

**Meal time mapping:**
```python
MEAL_TIMES = {
    'breakfast': (8, 0),
    'lunch': (12, 0),
    'snack': (15, 0),
    'dinner': (19, 30),
}
```

**Key changes:**
- Use `datetime` instead of `date` for `DTSTART`/`DTEND`
- Set local timezone
- Add `TRANSP: TRANSPARENT` for free/busy status
- Create 1-4 events per day instead of 1 all-day event

**Remove:** `format_day_summary()` function (no longer needed)

## Files Changed

| File | Change |
|------|--------|
| `lib/ics_generator.py` | Rewrite to create timed events per meal |
| `lib/meal_plan_parser.py` | Add snack extraction |
| `templates/meal_plan_template.py` | Add Snack section to template |
| `CLAUDE.md` | Update docs for new meal times |

**No changes needed:**
- `sync_calendar.py` (just calls the generator)
- `api_server.py` (serves the same ICS file)
- Existing meal plan files (snack just won't appear)

## Testing

1. Run `sync_calendar.py --dry-run`
2. Subscribe to ICS in Apple Calendar
3. Verify times display correctly and show as free
