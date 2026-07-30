"""Prompt for deriving a grid ("Cooking for Engineers" matrix) from a recipe.

The model turns a flat ingredient list + numbered steps into an ordered chain of
combine-groups: which ingredients are combined first, what's done to them, then
what's added next, ending in a terminal action (bake/simmer/serve). The renderer
turns that chain into the staircase-of-merged-cells matrix.
"""

GRID_PROMPT = """You convert a recipe into a compact "grid" that shows which ingredients are combined together and in what order.

## Ingredients (use these exact item names):
{ingredients}

## Steps:
{steps}

Produce a LINEAR chain of combine-groups. Each group names the ingredients added at that stage and the single action applied (e.g. "melt", "whisk", "mix", "fold in", "saute"). Groups are applied in order to one running mixture: group 1 is combined first, then group 2's ingredients are added to that and its action applied, and so on. Put any oven/pan prep or preheat lines in "prep". Put the final cooking action (e.g. "bake 350F, 30-40 min") in "finish".

Every ingredient above must appear in exactly one group, using its exact item name.

Respond with ONLY this JSON (no markdown, no commentary):
{{"prep": ["..."], "groups": [{{"action": "melt", "ingredients": ["unsalted butter"]}}, {{"action": "mix", "ingredients": ["sugar", "vanilla extract"]}}], "finish": "bake 350F, 30-40 min"}}"""
