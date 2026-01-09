# Meal Plan Auto-Generation Design

Date: 2026-01-09
Status: Approved
Priority: Medium

## Problem

No way to automatically generate weekly meal plan templates. User must manually create files each week.

## Solution

**LaunchAgent → Python script → Obsidian vault**

1. LaunchAgent runs daily at 6am
2. Script checks if meal plan for 2 weeks ahead exists
3. If not, creates from template with blank slots to fill in

## Template Structure

```markdown
# Meal Plan - Week 03 (Jan 13 - Jan 19, 2026)

## Monday
### Breakfast

### Lunch

### Dinner

### Notes


## Tuesday
### Breakfast

### Lunch

### Dinner

### Notes


## Wednesday
### Breakfast

### Lunch

### Dinner

### Notes


## Thursday
### Breakfast

### Lunch

### Dinner

### Notes


## Friday
### Breakfast

### Lunch

### Dinner

### Notes


## Saturday
### Breakfast

### Lunch

### Dinner

### Notes


## Sunday
### Breakfast

### Lunch

### Dinner

### Notes

```

All fields blank by default. User fills in `[[Recipe Name]]` links.

## File Naming

| Component | Format |
|-----------|--------|
| Folder | `Meal Plans/` in Obsidian vault |
| Filename | `2026-W03.md` (ISO week number) |
| Full path | `{vault}/Meal Plans/2026-W03.md` |

## Generation Logic

```python
def should_generate():
    """Check if we need to generate a meal plan."""
    today = date.today()

    # Target week is 2 weeks from now
    target_date = today + timedelta(weeks=2)
    target_week = target_date.isocalendar()

    filename = f"{target_week.year}-W{target_week.week:02d}.md"
    filepath = MEAL_PLANS_PATH / filename

    return not filepath.exists()
```

**Timing example:**
- Today: Monday Jan 6, 2026 (Week 02)
- Target: Week 04 (Jan 20-26)
- Creates: `Meal Plans/2026-W04.md`

## LaunchAgent Configuration

**File:** `~/Library/LaunchAgents/com.kitchenos.mealplan.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kitchenos.mealplan</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/chaseeasterling/KitchenOS/.venv/bin/python</string>
        <string>/Users/chaseeasterling/KitchenOS/generate_meal_plan.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/chaseeasterling/KitchenOS/meal_plan_generator.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/chaseeasterling/KitchenOS/meal_plan_generator.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/chaseeasterling/KitchenOS</string>
</dict>
</plist>
```

**Management:**
```bash
# Load/start
launchctl load ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

# Unload/stop
launchctl unload ~/Library/LaunchAgents/com.kitchenos.mealplan.plist

# Test run
.venv/bin/python generate_meal_plan.py
```

## Shopping List Integration

**Updated CLI:**
```bash
# Auto-detect current week's plan
python shopping_list.py

# Specify week explicitly
python shopping_list.py --week 2026-W03

# Legacy: custom file path
python shopping_list.py --plan "Custom Plan.md"
```

**Auto-detect logic:**
1. Get current ISO week
2. Look for `Meal Plans/{year}-W{week}.md`
3. If found, use it
4. If not, fall back to `Meal Plan.md` (backwards compatible)

## Files to Create

| File | Purpose |
|------|---------|
| `generate_meal_plan.py` | Main generation script |
| `templates/meal_plan_template.py` | Template formatting logic |
| `com.kitchenos.mealplan.plist` | LaunchAgent (copied to ~/Library/LaunchAgents/) |

## Files to Modify

| File | Change |
|------|--------|
| `shopping_list.py` | Add `--week` flag, auto-detect current week |
| `CLAUDE.md` | Document meal plan generation feature |

## CLI Interface

```bash
# Generate meal plan for 2 weeks ahead (normal operation)
python generate_meal_plan.py

# Generate for specific week
python generate_meal_plan.py --week 2026-W05

# Dry run (preview without creating)
python generate_meal_plan.py --dry-run

# Force regenerate (overwrites existing)
python generate_meal_plan.py --force --week 2026-W03
```

## Error Handling

| Error | Handling |
|-------|----------|
| Vault path doesn't exist | Exit with clear error |
| Meal Plans folder doesn't exist | Create it |
| File already exists | Skip (don't overwrite) |
| Permission error | Log and exit |

## Test Cases

1. **Normal generation** - Run on Monday, creates file 2 weeks ahead
2. **Already exists** - File exists, script exits cleanly
3. **Missing folder** - Creates `Meal Plans/` folder
4. **Dry run** - Prints what would be created, doesn't write
5. **Force flag** - Overwrites existing file
6. **Week override** - Creates specific week's plan
