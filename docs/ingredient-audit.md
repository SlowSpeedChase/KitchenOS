# Ingredient audit

- recipes scanned: **252**
- ingredient lines: **2758**
- recipes with at least one issue: **224** (89%)

| issue | lines | recipes | what it means |
|---|---:|---:|---|
| `parenthetical` | 556 | 142 | the name carries a parenthetical aside |
| `digits_in_item` | 249 | 76 | a number leaked into the ingredient name |
| `alternatives` | 202 | 98 | the name offers a choice ('x or y') |
| `unit_word_in_item` | 180 | 94 | a measurement word leaked into the ingredient name |
| `count_unit_on_pourable` | 146 | 91 | count unit on a pourable item |
| `whole_on_bulk` | 133 | 87 | 'whole' used for something poured or spooned |
| `unit_repeated_in_item` | 71 | 44 | the unit is duplicated into the ingredient name |
| `unknown_unit` | 66 | 38 | unrecognized unit |
| `leading_punctuation` | 10 | 9 | the name starts mid-phrase |
| `doubled_word` | 4 | 3 | a word repeats inside the ingredient name |
| `empty_item` | 2 | 1 | blank ingredient name |

## Examples

### `parenthetical`
- **2-Ingredient Tofu Naan!.md** — 'soft tofu (or silken tofu)' carries an aside
- **2-Ingredient Tofu Naan!.md** — 'pinch of salt (if using normal flour)' carries an aside
- **3010 Blueberry Banana Smoothie.md** — '(estimated) fiber blend' carries an aside
- **5-Ingredient Cottage Cheese Cookie Dough.md** — 'maple syrup (or honey)' carries an aside
- **5-Ingredient Cottage Cheese Cookie Dough.md** — 'vanilla extract (optional)' carries an aside
- **5-Ingredient Radish Salad.md** — 'lemon (zest and juice)' carries an aside
- …and 550 more (`--issue parenthetical` for all)

### `digits_in_item`
- **5 Min High-Fiber Shakshuka Breakfast.md** — 'each 2 eggs' contains a number
- **Arayes 🥙.md** — 'ground beef (85/15)' contains a number
- **Beefy Queso Loaded Potatoes.md** — 'ground beef (90/10)' contains a number
- **Black Bean Brownies.md** — 'black beans  250g after draining (1 15-oz can, drained and rinsed very well)' contains a number
- **Black Bean Brownies.md** — 'cocoa powder (10g)' contains a number
- **Black Bean Brownies.md** — 'quick oats  see nutrition link below for substitutions (40g)' contains a number
- …and 243 more (`--issue digits_in_item` for all)

### `alternatives`
- **150 Calorie Chicken Summer Rolls.md** — 'a large handful arugula or thinly sliced gem lettuce' offers a choice
- **2-Ingredient Tofu Naan!.md** — 'soft tofu (or silken tofu)' offers a choice
- **2-Ingredient Tofu Naan!.md** — 'butter or vegan butter for brushing' offers a choice
- **5-Ingredient Cottage Cheese Cookie Dough.md** — 'maple syrup (or honey)' offers a choice
- **Asian Style Garlic Noodles.md** — 'noodles or pasta' offers a choice
- **Baked Protein Oats.md** — 'nondairy milk (soymilk or milk of choice)' offers a choice
- …and 196 more (`--issue alternatives` for all)

### `unit_word_in_item`
- **2-Ingredient Tofu Naan!.md** — 'pinch of salt (if using normal flour)' contains unit word 'pinch'
- **200G Lentils And 1 Sweet Potato.md** — 'garlic cloves' contains unit word 'cloves'
- **Baked Protein Oats.md** — 'pinch of ground cloves' contains unit word 'pinch'
- **Beef Birria.md** — 'garlic cloves' contains unit word 'cloves'
- **Beef Birria.md** — 'ground clove' contains unit word 'clove'
- **Black Bean Brownies.md** — 'black beans  250g after draining (1 15-oz can, drained and rinsed very well)' contains unit word 'oz'
- …and 174 more (`--issue unit_word_in_item` for all)

### `count_unit_on_pourable`
- **150 Calorie Chicken Summer Rolls.md** — 'each rice paper sheets' has a density but a count unit 'whole'
- **200G Lentils And 1 Sweet Potato.md** — 'tomato sauce' has a density but a count unit 'whole'
- **200G Lentils And 1 Sweet Potato.md** — 'chopped parsley' has a density but a count unit 'whole'
- **Arayes 🥙.md** — 'parsley, finely chopped' has a density but a count unit 'whole'
- **Arayes 🥙.md** — 'cilantro, finely chopped' has a density but a count unit 'whole'
- **Asian Style Garlic Noodles.md** — 'dark soy sauce dark soy sauce (for color)' has a density but a count unit 'whole'
- …and 140 more (`--issue count_unit_on_pourable` for all)

### `whole_on_bulk`
- **150 Calorie Chicken Summer Rolls.md** — '1 whole each rice paper sheets' — rice is poured or spooned
- **200G Lentils And 1 Sweet Potato.md** — '1 whole tomato sauce' — sauce is poured or spooned
- **5 Min High-Fiber Shakshuka Breakfast.md** — '1 whole whole marinara sauce' — sauce is poured or spooned
- **5-Ingredient Cottage Cheese Cookie Dough.md** — '1 whole scoop vanilla protein powder' — powder is poured or spooned
- **Arayes 🥙.md** — '0.5 whole lemon, juice of' — juice is poured or spooned
- **Asian Style Garlic Noodles.md** — '1 whole dark soy sauce dark soy sauce (for color)' — sauce is poured or spooned
- …and 127 more (`--issue whole_on_bulk` for all)

### `unit_repeated_in_item`
- **19 Calorie Fudgy Brownies (Crouton).md** — unit 'whole' also starts the item 'whole egg whites egg whites'
- **5 Min High-Fiber Shakshuka Breakfast.md** — unit 'whole' also starts the item 'whole marinara sauce'
- **5-Ingredient Radish Salad.md** — unit 'whole' also starts the item 'whole radishes'
- **Blueberry Donut Holes (Cottage Cheese Or Yogurt).md** — unit 'whole' also starts the item 'whole blueberries'
- **Cacio E Pepe Beans And Broccoli.md** — unit 'whole' also starts the item 'whole broccoli crown'
- **Charred Cabbage + Sicilian Pesto.md** — unit 'whole' also starts the item 'whole caraflex cabbage (also known as sweetheart cabbage)'
- …and 65 more (`--issue unit_repeated_in_item` for all)

### `unknown_unit`
- **150 Calorie Chicken Summer Rolls.md** — unit 'handful' is unrecognized
- **3010 Blueberry Banana Smoothie.md** — unit 'scoop' is unrecognized
- **Boiled Egg With Soy Sauce Marinade And Kimchi.md** — unit 'minutes' is unrecognized
- **Boiled Egg With Soy Sauce Marinade And Kimchi.md** — unit 'stalks' is unrecognized
- **Budget Meal With Sopita And Crispy Cheese Tacos.md** — unit 'maseca masa mix' is unrecognized
- **Carnitas Batch Cook.md** — unit 'jar' is unrecognized
- …and 60 more (`--issue unknown_unit` for all)

### `leading_punctuation`
- **Beefy Queso Loaded Potatoes.md** — '% milk' starts mid-phrase
- **Braised Tofu.md** — '- inch piece fresh ginger, (finely chopped)' starts mid-phrase
- **Butter Biscuits.md** — 'and a quarter milk or buttermilk (original recipe)' starts mid-phrase
- **Chicken Souvlaki Bowl.md** — '% greek yogurt' starts mid-phrase
- **Creamy Chicken And Sun-Dried Tomato Soup.md** — ', shredded rotisserie chicken works great cooked chicken (about 3 cups)' starts mid-phrase
- **Healthy Blueberry Apple Oatmeal Cake.md** — '+ 2 tsp greek yogurt' starts mid-phrase
- …and 4 more (`--issue leading_punctuation` for all)

### `doubled_word`
- **Charred Cabbage + Sicilian Pesto.md** — 'lemon lemon' repeats 'lemon'
- **Creamy Vodka Tortiglioni & Burrata.md** — 'salt salt' repeats 'salt'
- **Creamy Vodka Tortiglioni & Burrata.md** — 'water water' repeats 'water'
- **One Pan Chicken & Potatoes.md** — 'mediterranean marinade marinade' repeats 'marinade'

### `empty_item`
- **Lime Cheesecake.md** — ingredient name is blank
- **Lime Cheesecake.md** — ingredient name is blank

