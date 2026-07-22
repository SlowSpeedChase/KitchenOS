"""Prompt for assessing how a recipe fits the user's personal food system.

Why an LLM rather than a calculation: the questions that matter here are mostly
judgements, not arithmetic. Which craving does this serve? Would it work as a
zero-prep buffer food? How hard does it lean on cheese? None of that is a
nutrient threshold.

The two that *are* nutritional — heart (LDL) and steady (blood sugar) — cannot
be computed today: `NutritionData` carries only calories/protein/carbs/fat, and
the local USDA store deliberately materializes no fiber or saturated fat. So
they are inferred here and written with `fit_needs_review: true`, per the
project's honest-about-inference rule, in a schema shaped so computed values
can replace them later without a rewrite.
"""

FIT_PROMPT = """You are helping tag a recipe against someone's personal food system.

## Their food system
{profile}

## The recipe
Name: {name}
Ingredients:
{ingredients}

## Your task
Judge this recipe against their system. Be honest — an unflattering answer is
more useful than a generous one. This person loves sweet, carby, salty and rich
food, and is trying to lower LDL cholesterol and avoid type 2 diabetes.

Fields:
- craving_lane: which craving this serves — "sweet", "carby", "salty", "rich", or "none"
- buffer_candidate: true only if it is genuinely near-zero-prep and could be
  eaten straight from the fridge/pantry when a craving hits. A recipe requiring
  cooking is false, however healthy.
- dairy_load: "none", "low", "medium", or "high" — how much cheese/butter/cream
  it leans on. Yogurt counts as low; saturated fat is the concern, not dairy itself.
- effort: "assembly" (no cooking), "quick" (under ~20 min), or "project"
- heart: true if this plausibly helps lower LDL — high fibre, unsaturated fats,
  legumes/oats/nuts, low saturated fat. False if it is cheese-, butter- or
  cream-forward.
- steady: true if it plausibly keeps blood sugar level — fibre and protein
  present, not refined-carb- or sugar-dominant.
- note: one short clause on the biggest caveat or the reason it fits. No more
  than 12 words.

Respond with ONLY this JSON (no markdown, no explanation):
{{"craving_lane": "sweet", "buffer_candidate": false, "dairy_load": "low", "effort": "quick", "heart": true, "steady": true, "note": "oats and nuts, no added sugar"}}"""
