"""Pull dates, meals, numbers and places out of one phrase. No model.

Two date rules live side by side because the two uses disagree on purpose:
planning a meal on "Wednesday" means the next Wednesday from today, while
opening "Wednesday" keeps the Siri web-navigation rule (this ISO week).
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MEALS = ("breakfast", "lunch", "dinner", "snack")
LOCATIONS = ("freezer", "fridge", "pantry", "counter")
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "dozen": 12}
SCALE_WORDS = {"double": 2.0, "triple": 3.0, "half": 0.5}
UNIT_WORDS = {"can": "can", "cans": "can", "bag": "bag", "bags": "bag", "jar": "jar",
              "jars": "jar", "bottle": "bottle", "bottles": "bottle", "box": "box",
              "boxes": "box", "carton": "carton", "cartons": "carton", "loaf": "loaf",
              "loaves": "loaf", "bunch": "bunch", "bunches": "bunch", "lb": "lb",
              "lbs": "lb", "pound": "lb", "pounds": "lb", "oz": "oz", "ounce": "oz",
              "ounces": "oz"}

_ITEM_STOP = {
    "add", "got", "bought", "picked", "grabbed", "up", "have", "we", "we're", "were",
    "are", "i", "i'm", "im", "am", "out", "of", "ran", "run", "used", "no", "more",
    "finished", "move", "put", "stick", "the", "to", "some", "my", "our", "please",
    "another", "in", "into", "on", "and", "is", "there",
} | set(NUMBER_WORDS) | set(UNIT_WORDS) | set(LOCATIONS)

_DATE = re.compile(
    r"\b(today|tonight|tomorrow|the next day|the day after|next week|this week"
    r"|(next )?(" + "|".join(DAYS) + r"))\b")
_SERVINGS = re.compile(
    r"\b(\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")\s+servings?\b")


def iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def week_monday(week: str) -> date:
    year, number = week.split("-W")
    return date.fromisocalendar(int(year), int(number), 1)


def _number(token: str) -> Optional[float]:
    if token in NUMBER_WORDS:
        return float(NUMBER_WORDS[token])
    try:
        return float(token)
    except ValueError:
        return None


@dataclass
class Slots:
    dates: list = field(default_factory=list)         # planning rule
    nav_dates: list = field(default_factory=list)     # this-ISO-week rule
    date_options: list = field(default_factory=list)  # "next friday": must be asked
    meal: Optional[str] = None
    scale: Optional[float] = None
    count: Optional[float] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    week: Optional[str] = None


def _clean(phrase: str) -> str:
    return phrase.lower().replace("’", "'")


def extract(phrase: str, *, today: date, week_start: Optional[date] = None,
            prev_date: Optional[date] = None) -> Slots:
    low = _clean(phrase)
    s = Slots()
    for m in _DATE.finditer(low):
        word = m.group(1)
        if word in ("today", "tonight"):
            plan = nav = today
        elif word == "tomorrow":
            plan = nav = today + timedelta(days=1)
        elif word in ("the next day", "the day after"):
            if prev_date is None:
                continue
            plan = nav = prev_date + timedelta(days=1)
        elif word == "next week":
            s.week = iso_week(today + timedelta(days=7))
            continue
        elif word == "this week":
            s.week = iso_week(today)
            continue
        else:
            idx = DAYS.index(m.group(3))
            coming = today + timedelta(days=(idx - today.weekday()) % 7)
            if m.group(2):
                s.date_options = [coming, coming + timedelta(days=7)]
                continue
            if week_start is not None:
                plan = nav = week_start + timedelta(days=idx)
            else:
                plan = coming
                nav = today - timedelta(days=today.weekday()) + timedelta(days=idx)
        s.dates.append(plan)
        s.nav_dates.append(nav)

    s.meal = next((m for m in MEALS if re.search(rf"\b{m}\b", low)), None)
    if s.meal is None and "tonight" in low:
        s.meal = "dinner"
    s.location = next((p for p in LOCATIONS if re.search(rf"\b{p}\b", low)), None)
    s.scale = next((v for w, v in SCALE_WORDS.items() if re.search(rf"\b{w}\b", low)), None)

    servings = _SERVINGS.search(low)
    if servings:
        s.count = _number(servings.group(1))

    tokens = re.findall(r"[a-z0-9.']+", low)
    for i, token in enumerate(tokens):
        value = _number(token)
        followed_by_servings = i + 1 < len(tokens) and tokens[i + 1].startswith("serving")
        if value is not None and not followed_by_servings:
            s.quantity = value
            break
    s.unit = next((UNIT_WORDS[t] for t in tokens if t in UNIT_WORDS), None)
    return s


def item_text(phrase: str) -> str:
    """The food being talked about, with verbs, numbers, units and places removed."""
    tokens = re.findall(r"[a-z']+", _clean(phrase))
    return " ".join(t for t in tokens if t not in _ITEM_STOP)
