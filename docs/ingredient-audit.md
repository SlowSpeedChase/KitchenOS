# Ingredient audit

- recipes scanned: **252**
- ingredient lines: **2755**
- recipes with an *actionable* issue: **139** (55%)
- recipes flagged by any rule incl. `info`: 213 (85%)

`info` lines read fine to a cook and are excluded from the headline —
"almond or cashew butter" is how recipes talk, not a defect.

| severity | issue | lines | recipes | what it means |
|---|---|---:|---:|---|
| `defect` | `unknown_unit` | 57 | 32 | unrecognized unit |
| `defect` | `leading_punctuation` | 9 | 8 | the name starts mid-phrase |
| `defect` | `empty_item` | 2 | 1 | blank ingredient name |
| `recoverable` | `gram_equivalent_discarded` | 71 | 22 | an exact weight is sitting unused in the name |
| `filler` | `count_unit_on_pourable` | 154 | 93 | count unit on a pourable item |
| `filler` | `whole_on_bulk` | 134 | 86 | 'whole' used for something poured or spooned |
| `filler` | `no_amount_stated` | 17 | 12 | the line says outright that no amount was given |
| `junk` | `cross_reference` | 12 | 4 | points at a note that wasn't kept |
| `junk` | `oven_temp_as_ingredient` | 1 | 1 | an oven temperature parsed as an ingredient |
| `junk` | `sponsor_code` | 1 | 1 | a sponsor/affiliate code came along |
| `info` | `parenthetical` | 494 | 138 | the name carries a parenthetical aside |
| `info` | `alternatives` | 196 | 97 | the name offers a choice ('x or y') |
| `info` | `digits_in_item` | 193 | 73 | a number leaked into the ingredient name |
| `info` | `unit_word_in_item` | 175 | 93 | a measurement word leaked into the ingredient name |

## Examples

### `parenthetical`
- **2-Ingredient Tofu Naan!.md** — 'soft tofu (or silken tofu)' carries an aside
- **2-Ingredient Tofu Naan!.md** — 'pinch of salt (if using normal flour)' carries an aside
- **3010 Blueberry Banana Smoothie.md** — '(estimated) fiber blend' carries an aside
- **5-Ingredient Cottage Cheese Cookie Dough.md** — 'maple syrup (or honey)' carries an aside
- **5-Ingredient Cottage Cheese Cookie Dough.md** — 'vanilla extract (optional)' carries an aside
- **5-Ingredient Radish Salad.md** — 'lemon (zest and juice)' carries an aside
- …and 488 more (`--issue parenthetical` for all)

### `alternatives`
- **150 Calorie Chicken Summer Rolls.md** — 'a large handful arugula or thinly sliced gem lettuce' offers a choice
- **2-Ingredient Tofu Naan!.md** — 'soft tofu (or silken tofu)' offers a choice
- **2-Ingredient Tofu Naan!.md** — 'butter or vegan butter for brushing' offers a choice
- **5-Ingredient Cottage Cheese Cookie Dough.md** — 'maple syrup (or honey)' offers a choice
- **Asian Style Garlic Noodles.md** — 'noodles or pasta' offers a choice
- **Baked Protein Oats.md** — 'nondairy milk (soymilk or milk of choice)' offers a choice
- …and 190 more (`--issue alternatives` for all)

### `digits_in_item`
- **5 Min High-Fiber Shakshuka Breakfast.md** — 'each 2 eggs' contains a number
- **Arayes 🥙.md** — 'ground beef (85/15)' contains a number
- **Beefy Queso Loaded Potatoes.md** — 'ground beef (90/10)' contains a number
- **Beefy Queso Loaded Potatoes.md** — '2% milk' contains a number
- **Black Bean Brownies.md** — 'black beans 250g after draining (1 15-oz can, drained and rinsed very well)' contains a number
- **Black Bean Brownies.md** — 'cocoa powder (10g)' contains a number
- …and 187 more (`--issue digits_in_item` for all)

### `unit_word_in_item`
- **2-Ingredient Tofu Naan!.md** — 'pinch of salt (if using normal flour)' contains unit word 'pinch'
- **200G Lentils And 1 Sweet Potato.md** — 'garlic cloves' contains unit word 'cloves'
- **Baked Protein Oats.md** — 'pinch of ground cloves' contains unit word 'pinch'
- **Beef Birria.md** — 'garlic cloves' contains unit word 'cloves'
- **Beef Birria.md** — 'ground clove' contains unit word 'clove'
- **Black Bean Brownies.md** — 'black beans 250g after draining (1 15-oz can, drained and rinsed very well)' contains unit word 'oz'
- …and 169 more (`--issue unit_word_in_item` for all)

### `count_unit_on_pourable`
- **150 Calorie Chicken Summer Rolls.md** — 'each rice paper sheets' has a density but a count unit 'whole'
- **200G Lentils And 1 Sweet Potato.md** — 'tomato sauce' has a density but a count unit 'whole'
- **200G Lentils And 1 Sweet Potato.md** — 'chopped parsley' has a density but a count unit 'whole'
- **Arayes 🥙.md** — 'parsley, finely chopped' has a density but a count unit 'whole'
- **Arayes 🥙.md** — 'cilantro, finely chopped' has a density but a count unit 'whole'
- **Asian Style Garlic Noodles.md** — 'dark soy sauce (for color)' has a density but a count unit 'whole'
- …and 148 more (`--issue count_unit_on_pourable` for all)

### `whole_on_bulk`
- **150 Calorie Chicken Summer Rolls.md** — '1 whole each rice paper sheets' — rice is poured or spooned
- **200G Lentils And 1 Sweet Potato.md** — '1 whole tomato sauce' — sauce is poured or spooned
- **5 Min High-Fiber Shakshuka Breakfast.md** — '1 whole marinara sauce' — sauce is poured or spooned
- **5-Ingredient Cottage Cheese Cookie Dough.md** — '1 whole scoop vanilla protein powder' — powder is poured or spooned
- **Arayes 🥙.md** — '0.5 whole lemon, juice of' — juice is poured or spooned
- **Asian Style Garlic Noodles.md** — '1 whole dark soy sauce (for color)' — sauce is poured or spooned
- …and 128 more (`--issue whole_on_bulk` for all)

### `gram_equivalent_discarded`
- **Black Bean Brownies.md** — 'cocoa powder (10g)' states an exact weight that is being thrown away
- **Black Bean Brownies.md** — 'quick oats see nutrition link below for substitutions (40g)' states an exact weight that is being thrown away
- **Black Bean Brownies.md** — 'coconut or vegetable oil see nutrition link for substitution notes (40g)' states an exact weight that is being thrown away
- **Black Bean Dip.md** — 'black beans, rinsed and drained (15.5 ounce)' states an exact weight that is being thrown away
- **Blueberry Rhubarb Muffins.md** — 'frozen blueberries (130g)' states an exact weight that is being thrown away
- **Braised Tofu.md** — 'thinly sliced red bell peppers see note 2 for more options (120g)' states an exact weight that is being thrown away
- …and 65 more (`--issue gram_equivalent_discarded` for all)

### `unknown_unit`
- **150 Calorie Chicken Summer Rolls.md** — unit 'handful' is unrecognized
- **3010 Blueberry Banana Smoothie.md** — unit 'scoop' is unrecognized
- **Boiled Egg With Soy Sauce Marinade And Kimchi.md** — unit 'minutes' is unrecognized
- **Boiled Egg With Soy Sauce Marinade And Kimchi.md** — unit 'stalks' is unrecognized
- **Budget Meal With Sopita And Crispy Cheese Tacos.md** — unit 'maseca masa mix' is unrecognized
- **Carnitas Batch Cook.md** — unit 'jar' is unrecognized
- …and 51 more (`--issue unknown_unit` for all)

### `no_amount_stated`
- **150 Calorie Chicken Summer Rolls.md** — 'a large handful arugula or thinly sliced gem lettuce' says outright that no amount was given
- **Charred Corn Salad With White Beans.md** — 'handful of fresh basil leaves, (slivered)' says outright that no amount was given
- **Chicken Gyro Bowls.md** — 'to your liking salt and pepper' says outright that no amount was given
- **Crispy Baked Chicken Thighs.md** — 'a handful fresh dill' says outright that no amount was given
- **Crispy Pasta Salad.md** — 'handful parsley (finely chopped)' says outright that no amount was given
- **Earl Grey Pie.md** — 'a few splashes heavy cream' says outright that no amount was given
- …and 11 more (`--issue no_amount_stated` for all)

### `cross_reference`
- **Blueberry Muffins.md** — 'fresh blueberries washed, drained, and picked-over, or frozen see note 1 (1 pint)' points at a note that wasn't kept
- **Braised Tofu.md** — 'oil from chinese chile oil or chile crisp see note 1 (sub neutral-flavored oil)' points at a note that wasn't kept
- **Braised Tofu.md** — 'thinly sliced red bell peppers see note 2 for more options (120g)' points at a note that wasn't kept
- **Braised Tofu.md** — 'chinese “light soy sauce” see note 3 (or regular store soy sauce)' points at a note that wasn't kept
- **Muhammara (Roasted Red Pepper Dip).md** — 'jar roasted red bell peppers or 3 medium/large red bell peppers see note 1 (16-ounce/450g)' points at a note that wasn't kept
- **Muhammara (Roasted Red Pepper Dip).md** — 'panko breadcrumbs, fresh breadcrumbs, or fine breadcrumbs see note 2 (40g)' points at a note that wasn't kept
- …and 6 more (`--issue cross_reference` for all)

### `leading_punctuation`
- **Beefy Queso Loaded Potatoes.md** — '2% milk' starts mid-phrase
- **Braised Tofu.md** — '- inch piece fresh ginger, (finely chopped)' starts mid-phrase
- **Butter Biscuits.md** — 'and a quarter milk or buttermilk' starts mid-phrase
- **Chicken Souvlaki Bowl.md** — '1% greek yogurt' starts mid-phrase
- **Healthy Blueberry Apple Oatmeal Cake.md** — '+ 2 tsp greek yogurt' starts mid-phrase
- **Rich Fudgy Chocolate Cake.md** — 'or about 1 and 1/4 cups pumpkin puree' starts mid-phrase
- …and 3 more (`--issue leading_punctuation` for all)

### `empty_item`
- **Lime Cheesecake.md** — ingredient name is blank
- **Lime Cheesecake.md** — ingredient name is blank

### `oven_temp_as_ingredient`
- **Charred Cabbage.md** — 'f 400' is an oven temperature, not an ingredient

### `sponsor_code`
- **High Protein Crispy Mozzarella Sticks.md** — '@fit.flour' carries a sponsor/affiliate code

