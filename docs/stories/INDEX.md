# User Stories Index

**Last Updated:** 2025-01-07

---

## Dashboard

| State | Count | Limit |
|-------|-------|-------|
| Active | 0 | 5 max |
| Ready | 0 | - |
| Draft | 0 | - |
| Done | 0 | - |

**Command:** `./scripts/story.sh status`

---

## Active (In Progress)

*None*

---

## Ready (Actionable)

*None*

---

## Draft (Needs Refinement)

*None*

---

## Done (Completed)

*None*

---

## Story Workflow

```
draft/ → ready/ → active/ → done/
  │        │         │        │
Ideas   Refined   Working   Merged
         with       on
       criteria   branch
```

**Commands:**
```bash
./scripts/story.sh status              # Dashboard
./scripts/story.sh new <title>         # Create draft
./scripts/story.sh promote US-NNN      # Move to next state
./scripts/story.sh list [state]        # List stories
```

**Rules:**
- Max 5 active stories
- Must have acceptance criteria before `ready/`
- Moving to `active/` creates git branch
- Branch naming: `US-NNN/brief-description`
