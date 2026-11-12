# Local FDC resolver: qualifiers, legumes, can sizes, portions (2026-11-11)

Fix commit `2ab34ce`. Invariant: CLAUDE.md, "The local FDC ranker must not let a
qualifier pick the food". Tests: `tests/test_fdc_resolve_modifiers.py`.

## The reported cases (real store, `use_cache=True, resolution_provider="none"`)

| Line | Before | After |
|---|---|---|
| `cherry tomatoes` / `cherry tomatoes, raw` / `tomatoes, cherry` | Cherries, sweet, raw (63 kcal/100 g) | Tomatoes, grape, raw (27) |
| `cannellini beans` | Beans, cannellini, **dry** (345) | Beans, cannellini, canned, drained (115) |
| `garbanzo beans, canned, drained` | Beans, pinto, canned | Chickpeas, canned, drained |
| 1 can `canned chickpeas, rinsed (15-ounce)` | 0 g ("no piece weight") | 255 g (15 oz × 0.6 drained) |
| 1 can `no-salt-added black beans, rinsed (15-ounce)` | 425 g (portion ledger, liquid included) | 255 g |
| 1 cup `cucumber, chopped` | 0 g ("no density") | 104 g |
| ½ cup `dill pickles, chopped` | 0 g | 71.5 g |
| 2 tbsp `dill, fresh` | 0 g | 1.1 g |

Two bugs turned up along the way and were fixed in the same pass:

- **FDC portion `amount` was ignored.** 3,463 of 36,763 portion rows are
  recorded per N units (`0.5 cup ricotta = 129 g`), and `resolve_local` read
  each one as per *one* unit. Ricotta came out at half its real weight per cup,
  peanut butter at double per tbsp.
- **Foundation records ship no portions.** Foundation outranks SR Legacy, so
  the portion-less copy won and the cup weight on its SR twin was never seen.
  Portions are now pooled across records with the same description.

## Blast radius

Method: the whole corpus (464 recipes with ingredients) resolved offline
before and after, line by line, then each changed line checked with
`resolution_guard.shares_a_food_word`. The first version of the head rule was
unconditional. It changed 1,049 lines in 378 recipes and broke plenty of lines
that had been right ("kosher salt" → dill pickles, "garlic cloves" → ground
cloves, "leek tops" → beef round). Every rule now fires only when some
candidate can satisfy it.

Final: **684 food changes and 169 gram changes, across 357 recipes.** Of the
food changes:

| Before → after | Lines |
|---|---:|
| no shared food word → shares one (fixed) | 177 |
| shares one → none (regressed) | 6 |
| neither | 19 |
| both share a word (mostly better variety/form) | 985 |

The 6 regressions are three `umeboshi paste` lines (Almond paste → cheese,
wrong both ways) and `kala namak` (soymilk → Black Russian).

Median change is 15 kcal per serving. 87 recipes moved by 50 kcal or more, 178
went up and 146 went down. 33 recipes had `nutrition_calories: null` and now
carry a value. The biggest swings are corrections: stocks resolved to meat
("Chicken, meatless" at 2,700 g), oils that weighed 0 g, "butter beans" as
butter, "flaky sea salt" as Chilean sea bass.

**Known still-wrong (unchanged in kind, all noisy lines):** mint → Mint julep
(the store has "Spearmint", not "mint"), "hash browns" → beans and brown rice,
"chipotle sauce" → worcestershire, "snow peas or sugar snap peas" → snow cone,
"cantalini" (typo) → green beans. Recipe lines with notes in them ("(see
ingredient notes)", "of choice") are still the main source of bad matches,
because `resolve_local` gets the raw item, not the cleaned key.

## Re-derivation

`backfill_nutrition.py --force --only …` was run on all 357 recipes, from this
worktree against the main DB. Result: 357 updated, 0 skipped, 0 failed. Every
written value matched the offline prediction. Each file was backed up to
`Recipes/.history/` first.

## Before/after kcal per serving (sorted by size of change)

| Recipe | kcal before | kcal after | Δ | coverage | review |
|---|---:|---:|---:|---:|:-:|
| Broccoli Cheddar Soup | — | 3687 | new | 1.0 | yes |
| Broiled Chicken Thigh Bites | — | 651 | new | 0.67 | yes |
| Cake-Mix Pumpkin Crunch Loaf | — | 838 | new | 0.67 | yes |
| Cheesy French Onion Hash Brown Casserole | — | 4034 | new | 0.93 | yes |
| Chicken Enchilada Soup | — | 243 | new | 0.86 |  |
| Chicken Noodle Soup With Quick Stock | — | 3359 | new | 0.82 | yes |
| Chorizo Egg Tacos | — | 1068 | new | 0.6 | yes |
| Coconut Cauliflower Curry | — | 86 | new | 0.76 | yes |
| Coconut Edamame Stew | — | 173 | new | 0.8 |  |
| Corn And Black Bean Scoopable Salad | — | 720 | new | 0.64 | yes |
| Crispy Chicken Thighs With Lemon Pepper Sauce | — | 669 | new | 0.57 | yes |
| Cumin Zucchini | — | 70 | new | 0.33 | yes |
| French Onion Soup With Cheese Toast | — | 4714 | new | 0.82 | yes |
| From-Scratch Pumpkin Crunch Loaf | — | 3910 | new | 0.94 | yes |
| Fudgy Black Bean Brownies | — | 202 | new | 0.79 | yes |
| Garlicky Lime Beef With Hidden Zucchini | — | 407 | new | 1.0 |  |
| Hawaiian Macaroni Salad | — | 1354 | new | 1.0 | yes |
| Homemade Crepe Manicotti | — | 2637 | new | 0.71 | yes |
| Homemade Vegan Mayo | — | 247 | new | 1.0 | yes |
| Lemon Caper Chicken Salad | — | 428 | new | 0.75 | yes |
| Mayo-Marinated Chicken Thigh Sandwich | — | 233 | new | 0.38 | yes |
| Mediterranean Chickpea Salad | — | 452 | new | 0.89 |  |
| Quick Breakfast Chilaquiles | — | 1051 | new | 0.57 | yes |
| Quick Shakshuka | — | 651 | new | 0.79 | yes |
| Red Wine Braised Short Ribs | — | 419 | new | 0.5 | yes |
| Roasted Garlic Eggplant With Garlic Butter | — | 587 | new | 1.0 |  |
| Silken Tofu Chocolate Mousse | — | 286 | new | 0.45 | yes |
| Smoky Fresh Pumpkin Chili | — | 100 | new | 0.82 |  |
| Sticky Sesame Tofu | — | 220 | new | 0.88 |  |
| Three Sisters Pumpkin Stew | — | 1005 | new | 0.6 | yes |
| Tofu Tikka Masala | — | 1798 | new | 0.76 | yes |
| Two-Ingredient Pumpkin Loaf | — | 1037 | new | 0.67 | yes |
| Vegan Egg Salad (Tofu Egg Salad) | — | 128 | new | 1.0 | yes |
| Life-Changing Homemade Chili Crisp | 428 | 1802 | +1374 | 0.79 | yes |
| 5 Min High-Fiber Shakshuka Breakfast | 1674 | 377 | -1297 | 0.86 | yes |
| No-Yeast Porridge Bread | 1752 | 1127 | -625 | 0.5 | yes |
| Daal And Roti Bosh | 1234 | 629 | -605 | 1.0 |  |
| Jammy Zucchini | 641 | 70 | -571 | 1.0 | yes |
| Goddess Salad | 1776 | 2247 | +471 | 0.8 |  |
| Iced Thai Tea | 659 | 199 | -460 | 0.9 | yes |
| Mom’S Tomato-Garlic Chutney | 1207 | 752 | -455 | 0.7 | yes |
| Charred Cabbage | 914 | 1314 | +400 | 0.93 |  |
| Homestyle Braised Tofu | 765 | 416 | -349 | 0.86 |  |
| Salmon Onigiri | 1222 | 874 | -348 | 0.92 |  |
| Peach & Carrot Deli Container Mocktail | 613 | 274 | -339 | 0.8 | yes |
| Cashew Cream, Many Ways | 521 | 829 | +308 | 0.8 | yes |
| Blended Chocolate Salted Caramel Chia Pudding Mousse | 1436 | 1162 | -274 | 0.9 |  |
| Spicy Baked Black Bean Nachos | 465 | 702 | +237 | 0.93 |  |
| Spicy Noodle Stir-Fry With Salt & Pepper Tofu | 304 | 533 | +229 | 0.87 |  |
| Indian Peanut Crunchies | 478 | 706 | +228 | 0.82 | yes |
| Chipotle Beef Tostadas | 1105 | 881 | -224 | 0.85 |  |
| Mint-Pistachio Pesto | 350 | 563 | +213 | 0.73 | yes |
| Saucy Glazed Pan-Fried Tempeh, 2 Ways | 501 | 305 | -196 | 0.69 | yes |
| Shepherds Pie | 1468 | 1279 | -189 | 0.96 |  |
| Thai Red Curry With Tofu | 441 | 258 | -183 | 0.88 |  |
| Earl Grey Pie | 4088 | 4270 | +182 | 1.0 | yes |
| Chicken In Yogurt And Spices | 547 | 366 | -181 | 0.94 |  |
| Savory Walnut Crunch | 458 | 638 | +180 | 0.88 |  |
| Buttermilk Fried “Chicken” With Cornbread & Dilly Slaw | 447 | 622 | +175 | 0.84 |  |
| Asian Style Garlic Noodles | 586 | 749 | +163 | 0.67 | yes |
| Borscht Recipe With Meat | 536 | 374 | -162 | 1.0 | yes |
| Chinese Eggplant | 283 | 134 | -149 | 0.92 | yes |
| Budget Meal With Sopita And Crispy Cheese Tacos | 1271 | 1128 | -143 | 1.0 |  |
| Blueberry Protein Biscuits | 1725 | 1866 | +141 | 0.93 | yes |
| Macarona Bi Laban | 1364 | 1487 | +123 | 0.93 |  |
| Saucy Beans | 369 | 247 | -122 | 1.0 |  |
| My Favorite Dal Tadka | 332 | 215 | -117 | 0.73 | yes |
| Adult Grilled Cheese With Chili Crisp | 329 | 443 | +114 | 0.8 |  |
| Extremely Easy Queso Sauce | 899 | 1011 | +112 | 0.7 | yes |
| Tomato-Shallot Butter | 118 | 228 | +110 | 0.89 |  |
| Rich Fudgy Chocolate Cake | 285 | 176 | -109 | 0.8 |  |
| Charred Corn Salad With White Beans | 502 | 394 | -108 | 1.0 |  |
| Boiled Egg With Soy Sauce Marinade And Kimchi | 2062 | 1955 | -107 | 0.64 | yes |
| Carnitas Batch Cook | 704 | 597 | -107 | 1.0 |  |
| Charred Sweet Potato Wedges | 270 | 163 | -107 | 1.0 | yes |
| Baked Mac And Cheese | 1825 | 1719 | -106 | 0.92 |  |
| Glazed Torn Beets With Pistachio Butter & Mint | 402 | 507 | +105 | 0.87 | yes |
| High-Protein Black Bean Salad | 552 | 449 | -103 | 1.0 |  |
| Za’Atar | 39 | 140 | +101 | 0.4 | yes |
| Southern Brown Gravy | 127 | 27 | -100 | 1.0 | yes |
| Chia-Misu | 482 | 383 | -99 | 0.83 | yes |
| Chicken Gyro Bowls | 890 | 791 | -99 | 0.95 |  |
| Roasted Beets With Whipped Goat Cheese Pistachio Vinaigrette | 490 | 391 | -99 | 1.0 |  |
| Creamy Baked Veggie Mac And Cheese | 500 | 407 | -93 | 1.0 |  |
| Macerated Berries With Basil & Mint | 24 | 114 | +90 | 0.83 | yes |
| Perfectly Sweet-Yet-Tart Plum Galette | 170 | 258 | +88 | 0.81 | yes |
| Crispy Indian-Ish Lentils With Rice & Yogurt | 519 | 606 | +87 | 0.8 |  |
| French Toast Casserole With Black Sesame Butter | 193 | 279 | +86 | 0.89 |  |
| Garlic Parmesan Beans | 296 | 380 | +84 | 1.0 |  |
| Homemade Enchilada Sauce And Enchilada Red Sauce | 812 | 895 | +83 | 0.94 |  |
| Loaded Mushroom Shawarma Flatbreads | 784 | 867 | +83 | 0.85 |  |
| Watermelon Feta Salad | 197 | 114 | -83 | 1.0 |  |
| Oven-Baked Polenta With Tomatoes & White Beans | 428 | 508 | +80 | 0.83 |  |
| Pasta & Chickpeas With Fried Capers & Tomato-Shallot Butter | 370 | 450 | +80 | 0.73 | yes |
| Miso Butter–Seared King Oyster “Scallops” | 119 | 194 | +75 | 0.83 |  |
| Baingan Bharta | 249 | 177 | -72 | 0.75 | yes |
| Malaysian Curry Noodle Soup | 552 | 482 | -70 | 0.78 | yes |
| Mexican Street Corn Salad | 102 | 169 | +67 | 1.0 | yes |
| Garlicky Asparagus & Beans With Lemon-Infused Olive Oil | 218 | 283 | +65 | 0.82 |  |
| Hannah’S Carrot Lox | 327 | 262 | -65 | 0.64 | yes |
| Hazelnut Dukkah | 870 | 806 | -64 | 1.0 |  |
| Indian-Spiced Charred Corn Salad | 122 | 186 | +64 | 0.79 | yes |
| Matcha Collagen Cloud Smoothie – Mark Hyman, Md | 388 | 324 | -64 | 1.0 |  |
| High-Protein Egg Salad | 1073 | 1135 | +62 | 1.0 | yes |
| Miso Peanut Ramen Bowls | 516 | 454 | -62 | 1.0 |  |
| Sticky Coconut Milk–Braised Tofu | 344 | 282 | -62 | 0.62 | yes |
| Creamy Tahini Sauce, 3 Ways | 2600 | 2539 | -61 | 0.87 | yes |
| Crispy Lentils | 179 | 239 | +60 | 0.67 | yes |
| Eggless London Fog Tres Leches Cake | 799 | 740 | -59 | 0.38 | yes |
| Baked Tofu & Kale In Tomato-Chipotle Sauce | 734 | 676 | -58 | 0.85 |  |
| Crispy Baked Tofu, 2 Ways | 335 | 393 | +58 | 0.94 |  |
| Slow Cooker Chicken Salad Sandwiches | 734 | 676 | -58 | 0.75 | yes |
| Greek Green Goddess Dip Recipe | 162 | 105 | -57 | 0.88 |  |
| High-Protein Bean Lentil Dip | 52 | 108 | +56 | 1.0 | yes |
| Strawberry Buttercream Frosting | 1174 | 1119 | -55 | 1.0 | yes |
| The Sexy Skillet Lasagna | 103 | 48 | -55 | 0.6 | yes |
| Charred Sweet Potatoes With Sun Dried Tomato-Date-Basil Crumble | 796 | 742 | -54 | 0.78 | yes |
| Creamy Chickpea Spinach Masala With Tadka | 441 | 388 | -53 | 0.68 | yes |
| “Cream”-Braised Leeks With Crispy Bits | 415 | 362 | -53 | 0.85 |  |
| Crema, 2 Ways | 3043 | 3093 | +50 | 0.86 | yes |
| Maple Sweet Potato Salad - With Whipped Tahini And Crispy Chickpeas | 691 | 642 | -49 | 1.0 | yes |
| Noodle Salad With Rainbow Veggies | 554 | 603 | +49 | 0.91 |  |
| Ranch Gordo Beans And Rice With Sweet Potatoes | 514 | 561 | +47 | 0.83 |  |
| Vietnamese Rice Noodle Bowls With Crispy Tofu & Mushrooms | 354 | 399 | +45 | 0.72 | yes |
| Korean Bbq Jackfruit Sandwiches With Creamy Sesame Slaw | 160 | 201 | +41 | 0.57 | yes |
| Chicken Fricassée (French Creamy Chicken Stew) (Crouton) | 773 | 812 | +39 | 1.0 |  |
| Caramelized Stone Fruit Crisp With Tahini Custard | 314 | 350 | +36 | 0.88 | yes |
| Chicken Fricassée (French Creamy Chicken Stew) | 771 | 807 | +36 | 0.94 |  |
| Chili Cornbread Casserole | 529 | 565 | +36 | 1.0 |  |
| Citrus-Braised Fennel With White Beans | 456 | 420 | -36 | 0.9 |  |
| Loaded Kogi Chicken Bowl | 480 | 515 | +35 | 0.79 | yes |
| Nutella Protein Dessert | 382 | 417 | +35 | 1.0 | yes |
| Creamy Baked Wild Rice With Carrots | 501 | 467 | -34 | 0.93 |  |
| Roasted Chickpea Salad | 884 | 850 | -34 | 0.88 |  |
| Collard Greens With Sesame-Miso Cream | 221 | 252 | +31 | 0.85 | yes |
| Creamy Tuscan Chicken | 446 | 415 | -31 | 0.91 | yes |
| Crispy & Savory Moong Dal Pancakes (Or Crepes) | 116 | 147 | +31 | 0.73 | yes |
| Chickpea Pancake With Sesame Greens | 836 | 866 | +30 | 0.82 | yes |
| Spicy “Honey” With Candied Jalapeños | 124 | 94 | -30 | 1.0 | yes |
| Throwback Ranch Dressing | 419 | 449 | +30 | 1.0 | yes |
| Cold Tofu With Coconut-Ginger-Lime Crisp | 211 | 239 | +28 | 0.54 | yes |
| Jammy Plantains And Black Beans In Charred Poblano Sauce | 339 | 311 | -28 | 0.79 | yes |
| Street Corn Sweet Potato Bowl | 739 | 767 | +28 | 0.92 |  |
| Braised Carrots & Chickpeas With Dill Gremolata | 434 | 407 | -27 | 0.94 |  |
| Creamy Tahini Lentils With Crispy Spiced Garlic | 421 | 448 | +27 | 0.78 | yes |
| All Hail Caesar Dressing | 258 | 284 | +26 | 0.92 |  |
| Easy Hoisin Dipping Sauce (3 Ingredients) | 841 | 867 | +26 | 1.0 |  |
| Oats With Chia Seeds & Yogurt Recipe | 832 | 806 | -26 | 1.0 |  |
| Smashed Beef Kabobs With Cucumber Yogurt | 500 | 474 | -26 | 0.83 |  |
| Spicy Mint & Cilantro Sauce | 61 | 87 | +26 | 0.8 | yes |
| Chipotle Adobo Chicken Burrito | 3009 | 2984 | -25 | 1.0 | yes |
| French Toast | 202 | 227 | +25 | 1.0 |  |
| Hash Brown Casserole | 559 | 534 | -25 | 1.0 |  |
| Pomegranate Molasses Vinaigrette | 235 | 260 | +25 | 1.0 | yes |
| Short Rib Birria Tacos | 908 | 933 | +25 | 1.0 |  |
| Vegan Swedish Meatballs | 122 | 147 | +25 | 0.8 |  |
| Yogurt Sauce, 3 Ways | 845 | 870 | +25 | 0.82 | yes |
| Chai-Spiced Custard Tart With Mango | 330 | 306 | -24 | 0.88 |  |
| Giant Drink Your Greens Stacked Water Of The Day | 173 | 149 | -24 | 0.62 | yes |
| White Chocolate Raspberry Protein Cookies | 156 | 132 | -24 | 0.73 | yes |
| Chamomile, Strawberry Jam & Triple-Berry Black Bean Brownies | 361 | 384 | +23 | 1.0 |  |
| Citrus-Date Vinaigrette | 50 | 73 | +23 | 0.82 |  |
| One Pan Vegetarian Dinner | 672 | 649 | -23 | 0.83 | yes |
| The Best Bread Pudding Recipe | 457 | 480 | +23 | 1.0 |  |
| 10-Minute Chili Garlic Noodles | 152 | 130 | -22 | 0.86 |  |
| Chile Lime Chipotle Chicken | 902 | 924 | +22 | 0.93 | yes |
| Dubai Chocolate Brownies | 242 | 220 | -22 | 0.91 |  |
| Peri Peri Chicken With Lemon Butter Sauce | 618 | 640 | +22 | 0.94 |  |
| Protein Pizza Pasta Salad | 740 | 762 | +22 | 0.9 |  |
| The Fancy Caesar Salad | 382 | 403 | +21 | 1.0 |  |
| Cold-Dressed Enoki Mushroom And Cucumber Salad | 53 | 73 | +20 | 0.85 |  |
| Dumpling Dipping Sauce | 10 | 30 | +20 | 0.83 | yes |
| High-Protein Chocolate Chia Pudding Recipe | 185 | 205 | +20 | 1.0 | yes |
| Lettuce Wraps | 101 | 121 | +20 | 1.0 | yes |
| Saucy Black Beans In Sofrito | 156 | 136 | -20 | 0.67 | yes |
| Crispy Fennel-Spiced Crumbs | 353 | 372 | +19 | 1.0 | yes |
| Roasted Garlic Dip | 405 | 386 | -19 | 1.0 | yes |
| Blueberry Muffins | 326 | 308 | -18 | 1.0 |  |
| Cheesy Herb Bread Pudding With Caramelized Leeks | 215 | 233 | +18 | 0.75 | yes |
| Chili Oil Crunch | 47 | 65 | +18 | 0.92 |  |
| Dark Chocolate Mousse With Raspberry Compote | 271 | 253 | -18 | 0.73 | yes |
| Edamame Salad With Chili Crisp | 143 | 125 | -18 | 0.8 | yes |
| High-Protein Bean Lentil Dip (Crouton) | 445 | 427 | -18 | 0.93 | yes |
| Preserved Lemons | 106 | 124 | +18 | 0.43 | yes |
| Black Bean Dip | 134 | 151 | +17 | 1.0 | yes |
| Muhammara (Roasted Red Pepper Dip) | 217 | 200 | -17 | 1.0 | yes |
| Velvety White Bean & Tomato Stew | 189 | 172 | -17 | 0.69 | yes |
| Zesty + Spicy Chicken Fusion Bowl | 791 | 808 | +17 | 1.0 |  |
| Creamy Mushroom Garlic Herb Chicken | 1879 | 1895 | +16 | 0.89 |  |
| Croissant Bread Pudding | 614 | 630 | +16 | 1.0 |  |
| Mayak Eggs Recipe By Tasty | 407 | 391 | -16 | 0.83 |  |
| Scrambled Shakshuka | 271 | 287 | +16 | 0.85 |  |
| Cosmic Brownie Protein Ice Cream | 1475 | 1460 | -15 | 0.89 |  |
| Cottage Cheese Blueberry Muffins | 70 | 55 | -15 | 0.86 | yes |
| Diner-Style Buttermilk Waffles | 332 | 317 | -15 | 0.75 | yes |
| Healthy Key Lime Pie | 149 | 164 | +15 | 0.86 |  |
| Lemon Lime Protein Bundt Cakes | 124 | 110 | -14 | 0.91 |  |
| Low Calorie Protein Fluff | 403 | 389 | -14 | 1.0 |  |
| Preserved Lemon Salsa | 68 | 82 | +14 | 1.0 | yes |
| Crispy Spiced Garlic | 25 | 12 | -13 | 1.0 | yes |
| Spiced Wine–Poached Figs With “Honey” | 113 | 100 | -13 | 0.58 | yes |
| Ethiopian Red Lentil Stew With Spiced Butter | 372 | 384 | +12 | 0.73 | yes |
| Heirloom Tomato Salad With Ricotta & Chile Oil | 109 | 97 | -12 | 0.82 | yes |
| Scoopable Green Salad | 2607 | 2619 | +12 | 0.93 | yes |
| Chicken Caldo B | 549 | 560 | +11 | 0.88 |  |
| Fermented Cashew Cheese | 209 | 198 | -11 | 0.86 |  |
| Grapefruit-Shallot Vinaigrette | 21 | 32 | +11 | 0.86 | yes |
| High Protein Crispy Mozzarella Sticks | 126 | 137 | +11 | 0.83 |  |
| Preserved Lemon Vinaigrette | 56 | 67 | +11 | 0.88 | yes |
| Protein Cabbage Wraps (Meatless) | 266 | 277 | +11 | 1.0 | yes |
| The Perfect Sweet Treat Sourdough Bread | 548 | 537 | -11 | 0.8 | yes |
| Chocolate Cream Pie | 1004 | 994 | -10 | 1.0 |  |
| Crispy Pasta Salad | 325 | 335 | +10 | 1.0 |  |
| Maple-Roasted Squash & Chickpeas With Mint-Pistachio Pesto | 274 | 284 | +10 | 0.78 | yes |
| Mojo Sauce | 119 | 129 | +10 | 0.8 |  |
| Orange Drizzle Cake | 431 | 441 | +10 | 0.83 |  |
| The Best Vegan Potato Salad | 208 | 218 | +10 | 1.0 | yes |
| Breakfast Lentils Vegan Porridge | 563 | 572 | +9 | 1.0 |  |
| Buttery Caper–Pine Nut Dressing | 570 | 579 | +9 | 1.0 |  |
| Crunchy Roasted Chickpeas, 3 Ways | 677 | 686 | +9 | 1.0 |  |
| Flourless Protein Chocolate Cake | 271 | 262 | -9 | 0.71 | yes |
| Butter Chicken Snack Wrap | 378 | 386 | +8 | 0.82 |  |
| Cauliflower Steak With Butter Bean Purée And Chimichurri | 5460 | 5468 | +8 | 0.77 | yes |
| Chopped Italian Sliders On Hawaiian Rolls | 1584 | 1592 | +8 | 1.0 | yes |
| Creamy Lentil Tomato Sauce With Chickpeas | 749 | 741 | -8 | 1.0 |  |
| Italian Basil & Parsley Salsa Verde | 114 | 122 | +8 | 1.0 | yes |
| Lemony Pasta With Sausage & Broccoli | 269 | 277 | +8 | 0.87 |  |
| Low Calorie Tiramisu | 58 | 50 | -8 | 1.0 | yes |
| Tofu 65 | 3054 | 3062 | +8 | 0.87 | yes |
| Baked Protein Oats | 352 | 359 | +7 | 1.0 |  |
| Brunch Tacos | 803 | 810 | +7 | 0.89 |  |
| Herby Shallot-Garlic Confit | 125 | 132 | +7 | 0.78 | yes |
| Korean Bbq Sauce | 385 | 392 | +7 | 0.75 | yes |
| Lemon-Garlic Brussels Sprouts With Rosemary | 168 | 175 | +7 | 0.92 | yes |
| Shaved Carrot Salad With Pickled Shallots & Fresh Herbs | 150 | 157 | +7 | 0.79 | yes |
| Smoky Seed Sprinkle | 470 | 463 | -7 | 1.0 | yes |
| Strawberry Hibiscus Refresher | 72 | 79 | +7 | 0.86 | yes |
| The Best Tofu Scramble | 1849 | 1856 | +7 | 1.0 | yes |
| Whipped Feta | 870 | 877 | +7 | 1.0 |  |
| White Bean Barley Salad Recipe | 484 | 491 | +7 | 0.94 |  |
| Cacio E Pepe Beans And Broccoli | 267 | 273 | +6 | 1.0 | yes |
| Cheesy Crunchies | 1013 | 1019 | +6 | 0.83 |  |
| Cherry Chia Cups | 161 | 155 | -6 | 1.0 |  |
| Creamy & Crunchy Beet Salad With Crispy Fennel Crumbs | 135 | 129 | -6 | 0.62 | yes |
| Creamy Chicken And Sun-Dried Tomato Soup | 998 | 1004 | +6 | 1.0 |  |
| Crispy Smashed Potatoes With Lots Of Saucy Options | 141 | 135 | -6 | 0.67 | yes |
| Crunchy Spiced Tofu Nuggets | 134 | 140 | +6 | 0.93 | yes |
| Greek Feta Dip | 244 | 238 | -6 | 0.91 |  |
| Healthier Strawberry Horchata | 822 | 816 | -6 | 1.0 |  |
| Osso Buco | 903 | 897 | -6 | 0.88 | yes |
| Queso Dip Recipe | 271 | 277 | +6 | 1.0 |  |
| Scrambled Chickpeas With Chile Yogurt Sauce And Za’Atar Pita | 659 | 665 | +6 | 0.79 | yes |
| Whipped Tofu Ricotta (Big Vegan Flavor) | 218 | 224 | +6 | 0.9 | yes |
| Chick-Fil-A Style Chicken Nuggets | 4561 | 4556 | -5 | 1.0 | yes |
| Chili Oil Crunch (Crouton) | 18 | 23 | +5 | 0.92 | yes |
| How To Make Perfect French Toast | 152 | 157 | +5 | 1.0 |  |
| Oven Roasted Chicken | 487 | 492 | +5 | 0.8 | yes |
| Roasted Garlic Sweet Potato Soup | 856 | 851 | -5 | 0.8 | yes |
| Slutty Brownie Recipe | 319 | 314 | -5 | 1.0 |  |
| Strawberry Brownies | 523 | 528 | +5 | 0.86 |  |
| Whipped Tofu Ricotta | 279 | 274 | -5 | 1.0 | yes |
| A Really Good Pot Of Saucy Beans | 55 | 59 | +4 | 0.6 | yes |
| Almond Flour Pancakes | 624 | 620 | -4 | 1.0 |  |
| Buttery Brown Rice With Warm Spices | 229 | 233 | +4 | 1.0 |  |
| Chocolate-Covered Dates With Pistachio Butter | 62 | 58 | -4 | 0.75 | yes |
| Fried Shallots | 997 | 1001 | +4 | 0.75 | yes |
| Garlic Butter Steak Bites | 817 | 813 | -4 | 1.0 | yes |
| Green Shakshuka | 626 | 630 | +4 | 0.92 |  |
| High Protein Low Cal Chicken Sandwich | 589 | 593 | +4 | 1.0 | yes |
| Jersey Mikes Sub Inspired Dense Bean Salad | 392 | 388 | -4 | 1.0 |  |
| Poppy Seed Vinaigrette | 118 | 122 | +4 | 0.83 |  |
| Roasted Chicken & Mediterranean Avocado Sala | 399 | 403 | +4 | 1.0 | yes |
| Smoothe Fiber Blend | 23 | 27 | +4 | 1.0 | yes |
| Sriracha Lime Chicken Bowls | 645 | 649 | +4 | 1.0 |  |
| Strawberry Sheet Cake | 553 | 557 | +4 | 1.0 |  |
| Sweet & Sour Tempeh Peanut Stir-Fry | 600 | 596 | -4 | 0.81 |  |
| Arayes 🥙 | 1251 | 1248 | -3 | 1.0 |  |
| Beef Birria | 515 | 518 | +3 | 1.0 |  |
| Beefy Queso Loaded Potatoes | 824 | 827 | +3 | 0.95 |  |
| Black Bean Brownies | 336 | 339 | +3 | 0.91 |  |
| Cardamom Pear Oatmeal | 939 | 942 | +3 | 1.0 |  |
| Cast Iron Cornbread | 260 | 257 | -3 | 1.0 |  |
| Chili Cheese Tortillas | 300 | 297 | -3 | 1.0 | yes |
| Creamy Vodka Tortiglioni & Burrata | 1330 | 1333 | +3 | 0.69 | yes |
| Crispy Spiced Cobbler Cake With Pears | 331 | 328 | -3 | 0.72 | yes |
| Customizable Grain Salad With Garlicky Spiced Oil & Fresh Herbs | 178 | 181 | +3 | 0.82 |  |
| Green Goddess Dressing | 745 | 748 | +3 | 1.0 | yes |
| Haferflocken, Joghurt & Banane Cake | 192 | 189 | -3 | 0.9 |  |
| High Protein Sweet Potato, Beef, And Cottage Cheese Bowl | 409 | 412 | +3 | 1.0 |  |
| Lemongrass Ginger Rice | 308 | 311 | +3 | 0.8 |  |
| Mediterranean Roasted Eggplant Salad | 528 | 525 | -3 | 0.75 | yes |
| Mushroom Carnitas Tacos | 238 | 241 | +3 | 0.86 |  |
| Oat Flour Pancakes | 109 | 112 | +3 | 1.0 |  |
| Rosemary Farrotto With Cheesy Pine Nuts | 479 | 476 | -3 | 0.81 |  |
| Seneyet Jaj O Batata Baked Chicken And Potatoes | 389 | 392 | +3 | 1.0 |  |
| Shaved Fennel Salad With Pears & Grapefruit-Shallot Vinaigrette | 167 | 170 | +3 | 0.71 | yes |
| Spanish Tortilla And Bread Pudding | 446 | 443 | -3 | 1.0 |  |
| Tiramisu Overnight Oats Recipe | 968 | 965 | -3 | 0.9 |  |
| Willa Jean Cornbread | 444 | 441 | -3 | 1.0 |  |
| Basic Baked Tofu | 111 | 113 | +2 | 0.8 | yes |
| Beef Steak Pepper Lunch Skillet | 475 | 477 | +2 | 0.94 |  |
| Blended Chia Pudding With Apple | 299 | 297 | -2 | 0.78 | yes |
| Braised Tofu | 551 | 549 | -2 | 0.84 |  |
| Butter Chicken | 504 | 506 | +2 | 1.0 |  |
| Cabbage Steaks | 96 | 94 | -2 | 1.0 | yes |
| Charred Cabbage In Spiced Tomatoes With Tahini | 246 | 244 | -2 | 1.0 |  |
| Cheese Stuffed Garlic Naan | 864 | 866 | +2 | 1.0 |  |
| Cherry Vanilla Breakfast Smoothie | 341 | 339 | -2 | 1.0 | yes |
| Chicken Souvlaki Bowl | 493 | 495 | +2 | 0.86 |  |
| Creamy Garlic Tofu | 323 | 325 | +2 | 1.0 |  |
| Garlicky Kale | 11 | 13 | +2 | 0.67 | yes |
| Ham Cheddar + Chive Protein Biscuits | 363 | 361 | -2 | 1.0 |  |
| Hardee's Biscuits | 144 | 142 | -2 | 1.0 |  |
| Homemade Pasta | 496 | 494 | -2 | 1.0 | yes |
| Jammy Roasted Eggplant | 185 | 187 | +2 | 1.0 | yes |
| Large Batch Freezer Biscuits | 158 | 156 | -2 | 1.0 |  |
| Marinated White Beans & Fennel With Spiced Za’Atar Oil | 101 | 103 | +2 | 0.67 | yes |
| Mushroom Bacon | 133 | 135 | +2 | 0.8 | yes |
| Nature’S Botox Gummies | 65 | 63 | -2 | 0.83 |  |
| Pomegranate-Glazed Tofu | 111 | 113 | +2 | 0.8 | yes |
| Quick Roasted Cauliflower | 41 | 43 | +2 | 1.0 | yes |
| Rolled Biscuits | 151 | 149 | -2 | 1.0 | yes |
| Wildly Crunchy Cornmeal Beans | 164 | 166 | +2 | 0.71 | yes |
| 2-Ingredient Tofu Naan! | 46 | 47 | +1 | 1.0 | yes |
| 3010 Blueberry Banana Smoothie | 465 | 466 | +1 | 0.86 |  |
| Best Homemade Brownies | 170 | 169 | -1 | 1.0 |  |
| Blueberry Rhubarb Muffins | 324 | 323 | -1 | 0.94 |  |
| Chicken Chimichangas | 546 | 547 | +1 | 0.91 |  |
| Chicken Chow Mein | 580 | 581 | +1 | 0.94 |  |
| Chocolate Lava Cake | 116 | 115 | -1 | 0.88 | yes |
| Chocolate Waffles | 254 | 253 | -1 | 1.0 |  |
| Crispy Baked Chicken Thighs | 291 | 290 | -1 | 1.0 | yes |
| Dilly Green Olive Dense Bean Salad | 403 | 402 | -1 | 0.95 |  |
| Easy Skillet Breakfast Potatoes | 259 | 260 | +1 | 1.0 | yes |
| Fudgy Skillet Brownies With Raspberry Swirl Ice Cream | 280 | 281 | +1 | 0.69 | yes |
| Ginger-Lime Marinade For Chicken | 96 | 95 | -1 | 1.0 |  |
| Greek-Style Chicken And Potatoes | 528 | 529 | +1 | 0.87 |  |
| Healthy Blueberry Apple Oatmeal Cake | 257 | 256 | -1 | 1.0 |  |
| Healthy Delicious Protein Chocolate Cake | 212 | 211 | -1 | 1.0 |  |
| Homemade Mcgriddle In Under 30 Minutes | 1518 | 1517 | -1 | 1.0 |  |
| How To Make The Best Chilaquiles Chilaquiles Rojos Recipe | 1129 | 1130 | +1 | 0.91 |  |
| I Can’T Believe It’S Not Chicken | 176 | 177 | +1 | 0.69 | yes |
| Moist &Amp; Fluffy One Bowl Vegan Lemon Blueberry Cake (Gluten Free Option) | 262 | 263 | +1 | 0.92 |  |
| My Weekly Herby Green Salad | 508 | 507 | -1 | 0.86 |  |
| Nashville Hot Chicken Nuggets | 58 | 59 | +1 | 1.0 | yes |
| Pistachio Chocolate Cookies | 326 | 325 | -1 | 1.0 |  |
| Protein Biscoff Cheesecake | 171 | 170 | -1 | 0.92 |  |
| Pumpkin Gnocchi | 710 | 709 | -1 | 1.0 | yes |
| Roasted Butternut Wedges | 69 | 70 | +1 | 0.88 |  |
| Salted Chocolate Brownie Balls | 169 | 168 | -1 | 1.0 | yes |
| Salted Honey Pistachio Cookies | 148 | 149 | +1 | 1.0 |  |
| Sheet Pan Chicken & Potatoes + Tzatziki Sauce Recipe | 2362 | 2363 | +1 | 1.0 | yes |
| Smoked Salmon Toasts | 303 | 302 | -1 | 1.0 |  |
| Soft & Chewy Ginger Cookies With Cardamom Sugar | 88 | 89 | +1 | 0.76 | yes |
| Spice-Roasted Whole Carrots | 213 | 212 | -1 | 0.86 | yes |
| Spiced Lentil Salad With Fresh Herbs | 200 | 201 | +1 | 0.83 | yes |
| Stealth Health Bean And Lentil Pasta | 440 | 439 | -1 | 0.89 |  |
