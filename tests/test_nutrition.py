"""Tests for nutrition data types."""

from lib.nutrition import NutritionData


class TestNutritionData:
    def test_create_nutrition_data(self):
        data = NutritionData(calories=450, protein=25, carbs=45, fat=18)
        assert data.calories == 450
        assert data.protein == 25
        assert data.carbs == 45
        assert data.fat == 18

    def test_add_nutrition_data(self):
        a = NutritionData(calories=200, protein=10, carbs=20, fat=8)
        b = NutritionData(calories=300, protein=15, carbs=25, fat=10)
        result = a + b
        assert result.calories == 500
        assert result.protein == 25
        assert result.carbs == 45
        assert result.fat == 18

    def test_multiply_nutrition_data(self):
        data = NutritionData(calories=200, protein=10, carbs=20, fat=8)
        result = data * 2
        assert result.calories == 400
        assert result.protein == 20
        assert result.carbs == 40
        assert result.fat == 16

    def test_nutrition_data_to_dict(self):
        data = NutritionData(calories=450, protein=25, carbs=45, fat=18)
        result = data.to_dict()
        assert result == {"calories": 450, "protein": 25, "carbs": 45, "fat": 18}

    def test_nutrition_data_from_dict(self):
        d = {"calories": 450, "protein": 25, "carbs": 45, "fat": 18}
        data = NutritionData.from_dict(d)
        assert data.calories == 450
        assert data.protein == 25

    def test_empty_nutrition_data(self):
        data = NutritionData.empty()
        assert data.calories == 0
        assert data.protein == 0
        assert data.carbs == 0
        assert data.fat == 0
