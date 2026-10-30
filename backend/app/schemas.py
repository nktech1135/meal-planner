from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.nutrients import BY_CODE

Kind = Literal["food", "supplement"]
State = Literal["raw", "cooked", "prepared"]
Basis = Literal["100g", "serving"]
WeighedState = Literal["as_is", "cooked"]
Meal = Literal["breakfast", "lunch", "dinner", "snack", "supplement"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: int
    email: str
    display_name: str
    is_admin: bool


# --- profile ----------------------------------------------------------------

class ProfileIn(BaseModel):
    sex: Literal["male", "female"] | None = None
    birth_date: date | None = None
    height_cm: float | None = Field(default=None, gt=0, lt=300)
    weight_kg: float | None = Field(default=None, gt=0, lt=700)
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] = "moderate"
    goal: Literal["lose", "maintain", "gain"] = "maintain"
    life_stage: Literal["none", "pregnant", "lactating"] = "none"
    timezone: str | None = None
    health_notes: str = Field(default="", max_length=4000)
    target_overrides: dict[str, dict[str, float | None]] = {}
    pinned_nutrients: list[str] = Field(default=[], max_length=40)
    unit_system: Literal["metric", "imperial"] = "metric"

    @field_validator("pinned_nutrients")
    @classmethod
    def _pinned(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(BY_CODE)
        if unknown:
            raise ValueError(f"Unknown nutrient codes: {sorted(unknown)}")
        return list(dict.fromkeys(v))

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        if v is None:
            return None
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return v

    @field_validator("target_overrides")
    @classmethod
    def _codes(cls, v: dict) -> dict:
        for code, o in v.items():
            if code not in BY_CODE:
                raise ValueError(f"Unknown nutrient '{code}'")
            if set(o) - {"min", "target", "max"}:
                raise ValueError("Overrides may only set min, target and max")
        return v


class ProfileOut(ProfileIn, ORM):
    pass


# --- foods ------------------------------------------------------------------

class PortionIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    gram_weight: float = Field(gt=0)


class PortionOut(PortionIn, ORM):
    id: int


class ComponentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float | None = None
    unit: str | None = None
    note: str | None = None


class FoodIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = None
    kind: Kind = "food"
    state: State | None = None
    cooking_method: str | None = None
    basis: Basis = "100g"
    serving_quantity: float | None = Field(default=None, gt=0)
    serving_unit: str | None = None
    serving_size_g: float | None = Field(default=None, gt=0)
    citation: str | None = Field(default=None, max_length=1000, description="Where the values came from, e.g. 'package label'")
    nutrients: dict[str, float] = {}
    portions: list[PortionIn] = []
    other_components: list[ComponentIn] = []

    @field_validator("nutrients")
    @classmethod
    def _codes(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - set(BY_CODE)
        if unknown:
            raise ValueError(f"Unknown nutrient codes: {sorted(unknown)}")
        if any(x < 0 for x in v.values()):
            raise ValueError("Nutrient amounts cannot be negative")
        return v


class FoodSummary(ORM):
    id: int
    name: str
    brand: str | None
    kind: str
    state: str | None
    cooking_method: str | None
    basis: str
    serving_quantity: float | None
    serving_unit: str | None
    serving_size_g: float | None
    source: str
    source_data_type: str | None
    category: str | None = None
    trust_level: str
    owner_id: int | None
    macros: dict[str, float] = {}


class FoodOut(FoodSummary):
    source_id: str | None
    source_url: str | None
    citation: str | None
    fetched_at: datetime | None
    created_at: datetime
    nutrients: dict[str, float]
    derivations: dict[str, str | None] = {}
    portions: list[PortionOut]
    other_components: list[dict]


class NutrientDefOut(BaseModel):
    code: str
    name: str
    unit: str
    category: str


# --- sources ----------------------------------------------------------------

class SourceOut(BaseModel):
    key: str
    name: str
    description: str
    homepage: str
    trust_level: str
    paid: bool
    enabled: bool
    disabled_reason: str | None


class SearchHitOut(BaseModel):
    source: str
    source_id: str
    name: str
    brand: str | None
    kind: str
    trust_level: str
    basis: str
    data_type: str | None
    summary: dict[str, float]
    detail: str | None
    imported_food_id: int | None = None


class ImportIn(BaseModel):
    source_id: str = Field(min_length=1, max_length=120)
    name_hint: str | None = None


# --- cooking yields / conversions --------------------------------------------

class YieldIn(BaseModel):
    raw_food_id: int
    cooked_food_id: int | None = None
    method: str = Field(min_length=1, max_length=80)
    yield_factor: float | None = Field(default=None, gt=0, le=10)
    raw_weight_g: float | None = Field(default=None, gt=0)
    cooked_weight_g: float | None = Field(default=None, gt=0)
    retention: dict[str, float] = {}
    retention_profile_code: int | None = None  # USDA retention table profile; fills `retention`
    basis: Literal["measured", "published", "derived"] = "measured"
    citation: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("retention")
    @classmethod
    def _retention(cls, v: dict[str, float]) -> dict[str, float]:
        for code, f in v.items():
            if code not in BY_CODE:
                raise ValueError(f"Unknown nutrient '{code}'")
            if not 0 <= f <= 1.5:
                raise ValueError("Retention factors are fractions (0–1.5)")
        return v


class YieldOut(ORM):
    id: int
    raw_food_id: int
    cooked_food_id: int | None
    generated_by: str | None = None
    method: str
    yield_factor: float
    retention: dict[str, float]
    basis: str
    trust_level: str
    citation: str | None
    notes: str | None
    owner_id: int | None


class DeriveIn(BaseModel):
    raw_food_id: int
    cooked_food_id: int


class CalculateIn(BaseModel):
    food_id: int | None = None
    recipe_id: int | None = None
    quantity: float = Field(gt=0)
    unit: str = "g"
    weighed_state: WeighedState = "as_is"
    yield_id: int | None = None


class NutritionOut(BaseModel):
    nutrients: dict[str, float]
    grams: float | None
    trust_level: str
    other_components: list[dict]
    notes: list[str]


# --- recipes ----------------------------------------------------------------

class IngredientIn(BaseModel):
    food_id: int
    grams: float = Field(gt=0)
    weighed_state: WeighedState = "as_is"
    yield_id: int | None = None
    note: str = Field(default="", max_length=200)


class IngredientOut(IngredientIn, ORM):
    id: int
    food_name: str = ""


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    servings: float = Field(default=1, gt=0)
    cooked_weight_g: float | None = Field(default=None, gt=0)
    notes: str = Field(default="", max_length=4000)
    ingredients: list[IngredientIn] = []


class RecipeOut(ORM):
    id: int
    name: str
    servings: float
    cooked_weight_g: float | None
    notes: str
    ingredients: list[IngredientOut]
    nutrition: dict | None = None
    updated_at: datetime


# --- log --------------------------------------------------------------------

class LogIn(BaseModel):
    consumed_at: datetime | None = None
    meal: Meal = "snack"
    food_id: int | None = None
    recipe_id: int | None = None
    quantity: float = Field(gt=0)
    unit: str = "g"
    weighed_state: WeighedState = "as_is"
    yield_id: int | None = None
    note: str = Field(default="", max_length=500)


class LogOut(ORM):
    id: int
    consumed_at: datetime
    meal: str
    food_id: int | None
    recipe_id: int | None
    label: str
    quantity: float
    unit: str
    weighed_state: str
    yield_id: int | None
    grams: float | None
    is_supplement: bool
    nutrients: dict[str, float]
    other_components: list[dict]
    trust_level: str
    calc_notes: list[str]
    note: str


# --- advisor ----------------------------------------------------------------

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: int | None = None


class ChatMessageOut(BaseModel):
    role: str
    text: str
    tools_used: list[str] = []
    created_at: datetime


class ConversationOut(ORM):
    id: int
    title: str
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[ChatMessageOut]


class LogUpdate(BaseModel):
    consumed_at: datetime | None = None
    meal: Meal | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    weighed_state: WeighedState | None = None
    yield_id: int | None = None
    note: str | None = Field(default=None, max_length=500)


class CopyIn(BaseModel):
    from_date: date
    to_date: date
    meal: Meal | None = None  # copy just this meal (default: the whole day)
    to_meal: Meal | None = None


class SuggestionOut(BaseModel):
    food_id: int | None
    recipe_id: int | None
    label: str
    kind: str
    trust_level: str
    quantity: float
    unit: str
    weighed_state: str
    yield_id: int | None
    meal: str
    times: int
    last_used: datetime
    energy_kcal: float | None


class SavedMealItemIn(BaseModel):
    food_id: int | None = None
    recipe_id: int | None = None
    quantity: float = Field(gt=0)
    unit: str = "g"
    weighed_state: WeighedState = "as_is"
    yield_id: int | None = None


class SavedMealIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_meal: Meal = "snack"
    items: list[SavedMealItemIn] = Field(min_length=1)


class SavedMealItemOut(SavedMealItemIn, ORM):
    id: int
    label: str


class SavedMealOut(ORM):
    id: int
    name: str
    default_meal: str
    items: list[SavedMealItemOut]


class SavedMealFromLog(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    date: date
    meal: Meal


class SavedMealLogIn(BaseModel):
    meal: Meal | None = None
    consumed_at: datetime | None = None


class BodyIn(BaseModel):
    weight_kg: float | None = Field(default=None, gt=20, lt=700)
    body_fat_pct: float | None = Field(default=None, gt=1, lt=75)
    waist_cm: float | None = Field(default=None, gt=30, lt=300)
    note: str = Field(default="", max_length=500)


class BodyOut(BodyIn, ORM):
    date: date
