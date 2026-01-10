"""Nutrition data types for macro tracking."""

from dataclasses import dataclass
from typing import Self


@dataclass
class NutritionData:
    """Nutrition values per serving."""
    calories: int
    protein: int
    carbs: int
    fat: int

    def __add__(self, other: Self) -> Self:
        return NutritionData(
            calories=self.calories + other.calories,
            protein=self.protein + other.protein,
            carbs=self.carbs + other.carbs,
            fat=self.fat + other.fat,
        )

    def __mul__(self, multiplier: int | float) -> Self:
        return NutritionData(
            calories=int(self.calories * multiplier),
            protein=int(self.protein * multiplier),
            carbs=int(self.carbs * multiplier),
            fat=int(self.fat * multiplier),
        )

    def to_dict(self) -> dict:
        return {
            "calories": self.calories,
            "protein": self.protein,
            "carbs": self.carbs,
            "fat": self.fat,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            calories=d.get("calories", 0),
            protein=d.get("protein", 0),
            carbs=d.get("carbs", 0),
            fat=d.get("fat", 0),
        )

    @classmethod
    def empty(cls) -> Self:
        return cls(calories=0, protein=0, carbs=0, fat=0)
