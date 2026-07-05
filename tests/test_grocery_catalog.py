from lib.grocery_catalog import assign_category, shoppable_quantity


def test_assign_category_by_item():
    assert assign_category("mayonnaise") == "pantry"
    assert assign_category("chicken thighs") == "meat"
    assert assign_category("red onion") == "produce"


def test_assign_category_word_subset():
    # "boneless skinless chicken thighs" should still hit "chicken thighs"
    assert assign_category("boneless skinless chicken thighs") == "meat"


def test_assign_category_unknown_is_other():
    assert assign_category("dragonfruit foam") == "other"


def test_package_round_up_volume():
    # 1.5 cups mayo, 3.5-cup jar -> 1 jar
    assert shoppable_quantity("mayonnaise", "1.5", "cup") == {"amount": "1", "unit": "jar (30 oz)"}


def test_package_round_up_needs_two():
    # 8 cups mayo -> ceil(8/3.5) = 3 jars
    assert shoppable_quantity("mayonnaise", "8", "cup") == {"amount": "3", "unit": "jars (30 oz)"}


def test_buy_unit_weight_round_up():
    # 4.4 lb potatoes, no package -> 5 lb
    assert shoppable_quantity("potatoes", "4.4", "lb") == {"amount": "5", "unit": "lb"}


def test_count_package_dozen():
    assert shoppable_quantity("eggs", "1", "ct") == {"amount": "1", "unit": "dozen (12 ct)"}


def test_unknown_item_native_round_up():
    assert shoppable_quantity("dragonfruit foam", "1.2", "cup") == {"amount": "2", "unit": "cup"}


def test_no_amount_returns_blank():
    assert shoppable_quantity("salt", None, "to taste") == {"amount": "", "unit": ""}
    assert shoppable_quantity("salt", "", "") == {"amount": "", "unit": ""}
