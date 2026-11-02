from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on password change/reset or deactivation; sessions carrying an older value are rejected.
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped["Profile | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sex: Mapped[str | None] = mapped_column(String(10))  # male | female (used for reference intakes)
    birth_date: Mapped[date | None] = mapped_column(Date)
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    activity_level: Mapped[str] = mapped_column(String(20), default="moderate")
    goal: Mapped[str] = mapped_column(String(20), default="maintain")  # lose | maintain | gain
    life_stage: Mapped[str] = mapped_column(String(20), default="none")  # none | pregnant | lactating
    timezone: Mapped[str | None] = mapped_column(String(64))  # IANA name; None = not set yet (UTC used)
    # Free text the advisor sees: conditions, medications, dietary pattern, allergies.
    health_notes: Mapped[str] = mapped_column(Text, default="")
    # {nutrient_code: {"min": x, "target": y, "max": z}} — overrides computed targets.
    target_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nutrients always shown on the condensed day view, besides energy, macros and anything flagged.
    pinned_nutrients: Mapped[list] = mapped_column(JSON, default=list)
    unit_system: Mapped[str] = mapped_column(String(10), default="metric")  # metric | imperial (display only)
    # Food databases (Food.source keys) this user doesn't want in search results, e.g. ["ciqual", "bls"].
    hidden_sources: Mapped[list] = mapped_column(JSON, default=list)
    # Database ranked first among generic search results (None = USDA FoodData Central).
    preferred_source: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class Food(Base):
    """A food, ingredient, product or supplement with nutrient values on a stated basis.

    ``basis`` is ``100g`` (amounts per 100 g) or ``serving`` (amounts per label serving,
    typical for supplements, where ``serving_quantity`` × ``serving_unit`` is one serving).
    Foods with ``owner_id`` NULL are shared (imported from a source); others are private.
    """

    __tablename__ = "foods"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_food_source"),
        Index("ix_foods_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="food")  # food | supplement
    state: Mapped[str | None] = mapped_column(String(20))  # raw | cooked | prepared | None (n/a)
    cooking_method: Mapped[str | None] = mapped_column(String(60))
    basis: Mapped[str] = mapped_column(String(10), default="100g")
    serving_quantity: Mapped[float | None] = mapped_column(Float)
    serving_unit: Mapped[str | None] = mapped_column(String(80))
    serving_size_g: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(40), default="manual")
    source_id: Mapped[str | None] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_data_type: Mapped[str | None] = mapped_column(String(60))  # e.g. FDC "Foundation", "Branded"
    category: Mapped[str | None] = mapped_column(String(120))  # e.g. FDC food category "Poultry Products"
    barcode: Mapped[str | None] = mapped_column(String(32), index=True)  # GTIN/UPC/EAN digits, leading zeros removed
    ingredients: Mapped[str | None] = mapped_column(Text)  # label ingredient list (branded products)
    trust_level: Mapped[str] = mapped_column(String(20))
    citation: Mapped[str | None] = mapped_column(Text)
    # Unmapped label components, e.g. supplement botanicals: [{"name","amount","unit"}]
    other_components: Mapped[list] = mapped_column(JSON, default=list)
    source_payload: Mapped[dict | None] = mapped_column(JSON)  # raw upstream record, kept for audit

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    nutrients: Mapped[list["FoodNutrient"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    portions: Mapped[list["FoodPortion"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    def nutrient_map(self) -> dict[str, float]:
        return {n.nutrient_code: n.amount for n in self.nutrients}


class FoodNutrient(Base):
    __tablename__ = "food_nutrients"

    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), primary_key=True)
    nutrient_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    amount: Mapped[float] = mapped_column(Float)
    derivation: Mapped[str | None] = mapped_column(String(120))  # e.g. FDC "Analytical", "Calculated"


class FoodPortion(Base):
    __tablename__ = "food_portions"

    id: Mapped[int] = mapped_column(primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    gram_weight: Mapped[float] = mapped_column(Float)


class CookingYield(Base):
    """Raw → cooked mass conversion: cooked_weight = raw_weight × yield_factor.

    ``retention`` optionally holds per-nutrient retention factors (fraction of the raw
    nutrient remaining after cooking, e.g. from the USDA Table of Nutrient Retention
    Factors). Nutrients without a factor are assumed fully retained, and results are
    marked as such.
    """

    __tablename__ = "cooking_yields"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"), index=True)
    cooked_food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(80))  # e.g. "roasted", "boiled", "pan-fried"
    yield_factor: Mapped[float] = mapped_column(Float)
    retention: Mapped[dict] = mapped_column(JSON, default=dict)
    basis: Mapped[str] = mapped_column(String(20))  # measured | published | derived
    trust_level: Mapped[str] = mapped_column(String(20))
    citation: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    generated_by: Mapped[str | None] = mapped_column(String(40))  # e.g. "usda-pairs" for yields derived in bulk

    raw_food: Mapped[Food] = relationship(foreign_keys=[raw_food_id])
    cooked_food: Mapped[Food | None] = relationship(foreign_keys=[cooked_food_id])


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    servings: Mapped[float] = mapped_column(Float, default=1)
    cooked_weight_g: Mapped[float | None] = mapped_column(Float)  # weigh the finished dish for best accuracy
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        cascade="all, delete-orphan", order_by="RecipeIngredient.position", lazy="selectin"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="RESTRICT"))
    grams: Mapped[float] = mapped_column(Float)
    # "as_is": grams are of the food as described. "cooked": grams were weighed after
    # cooking a raw food, converted back through ``yield_id``.
    weighed_state: Mapped[str] = mapped_column(String(10), default="as_is")
    yield_id: Mapped[int | None] = mapped_column(ForeignKey("cooking_yields.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(String(200), default="")

    food: Mapped[Food] = relationship(lazy="selectin")


class LogEntry(Base):
    """One thing a user ate or took. Nutrients are snapshotted at logging time so
    later edits to foods or recipes don't silently rewrite history."""

    __tablename__ = "log_entries"
    __table_args__ = (Index("ix_log_user_time", "user_id", "consumed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meal: Mapped[str] = mapped_column(String(20), default="snack")  # breakfast | lunch | dinner | snack | supplement
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="SET NULL"))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))  # g | serving | portion:<id>
    weighed_state: Mapped[str] = mapped_column(String(10), default="as_is")
    yield_id: Mapped[int | None] = mapped_column(ForeignKey("cooking_yields.id", ondelete="SET NULL"))
    grams: Mapped[float | None] = mapped_column(Float)  # resolved mass of the food as described, if known
    is_supplement: Mapped[bool] = mapped_column(Boolean, default=False)
    nutrients: Mapped[dict] = mapped_column(JSON, default=dict)
    other_components: Mapped[list] = mapped_column(JSON, default=list)
    trust_level: Mapped[str] = mapped_column(String(20))  # weakest trust among contributing data
    calc_notes: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(String(500), default="")
    # Who logged it, when that wasn't the user (someone they gave access to their profile).
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])

    @property
    def added_by(self) -> str | None:
        """The name of whoever logged it, if that wasn't the user themselves."""
        if self.created_by is None or self.created_by_id == self.user_id:
            return None
        return self.created_by.display_name or self.created_by.email


class AdvisorConversation(Base):
    __tablename__ = "advisor_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    messages: Mapped[list["AdvisorMessage"]] = relationship(
        cascade="all, delete-orphan", order_by="AdvisorMessage.id", lazy="selectin"
    )


class AdvisorMessage(Base):
    """A raw Messages-API turn. ``content`` is stored exactly as exchanged (including
    thinking and tool blocks) so the history can be replayed append-only."""

    __tablename__ = "advisor_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[list] = mapped_column(JSON)
    is_user_prompt: Mapped[bool] = mapped_column(Boolean, default=False)  # a typed message (vs. tool results)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    """A UI-managed application setting. Secret values are stored encrypted (see settings_store)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SavedMeal(Base):
    """A named group of items the user logs together (e.g. "usual breakfast")."""

    __tablename__ = "saved_meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    default_meal: Mapped[str] = mapped_column(String(20), default="snack")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["SavedMealItem"]] = relationship(
        cascade="all, delete-orphan", order_by="SavedMealItem.position", lazy="selectin")


class SavedMealItem(Base):
    __tablename__ = "saved_meal_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    saved_meal_id: Mapped[int] = mapped_column(ForeignKey("saved_meals.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    weighed_state: Mapped[str] = mapped_column(String(10), default="as_is")
    yield_id: Mapped[int | None] = mapped_column(ForeignKey("cooking_yields.id", ondelete="SET NULL"))


class FormChoice(Base):
    """A user's answer to "which form is this?" for an unconverted label component."""

    __tablename__ = "form_choices"
    __table_args__ = (UniqueConstraint("user_id", "food_id", "component_name", name="uq_form_choice"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))
    component_name: Mapped[str] = mapped_column(String(200))
    nutrient_code: Mapped[str] = mapped_column(String(40))
    option_key: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetentionProfile(Base):
    """A row group of the USDA Table of Nutrient Retention Factors (fraction of each nutrient retained)."""

    __tablename__ = "retention_profiles"

    code: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    food_group: Mapped[int] = mapped_column(Integer, index=True)
    description: Mapped[str] = mapped_column(String(255))
    factors: Mapped[dict] = mapped_column(JSON, default=dict)  # {nutrient_code: fraction}
    release: Mapped[str] = mapped_column(String(80))


class ImportJob(Base):
    """A background dataset import started from the admin UI."""

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset: Mapped[str] = mapped_column(String(40))
    release: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BodyMeasurement(Base):
    """One day's body measurements (any subset)."""

    __tablename__ = "body_measurements"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_body_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    waist_cm: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Exercise(Base):
    """One workout, entered by hand or imported from an activity file. ``kcal`` is net energy (above resting),
    which is added to that day's energy target."""

    __tablename__ = "exercises"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_exercise_user_external"),
                      Index("ix_exercises_user_date", "user_id", "date"))

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)  # in the user's timezone
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    name: Mapped[str] = mapped_column(String(200))
    activity_code: Mapped[str | None] = mapped_column(String(5))  # 2024 Adult Compendium code
    met: Mapped[float | None] = mapped_column(Float)
    duration_min: Mapped[float] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    reported_kcal: Mapped[float | None] = mapped_column(Float)  # gross, from a device or entered by hand
    kcal: Mapped[float] = mapped_column(Float, default=0)
    kcal_method: Mapped[str] = mapped_column(String(20), default="none")  # compendium | device | entered | none
    calc_note: Mapped[str] = mapped_column(String(300), default="")
    weight_kg: Mapped[float | None] = mapped_column(Float)  # the weight used for the estimate
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | fit | tcx | gpx
    external_id: Mapped[str | None] = mapped_column(String(64))  # de-duplicates imports
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PlanItem(Base):
    """Something the user intends to eat or take on a future (or current) day."""

    __tablename__ = "plan_items"
    __table_args__ = (Index("ix_plan_user_date", "user_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    meal: Mapped[str] = mapped_column(String(20), default="dinner")
    position: Mapped[int] = mapped_column(Integer, default=0)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    weighed_state: Mapped[str] = mapped_column(String(10), default="as_is")
    yield_id: Mapped[int | None] = mapped_column(ForeignKey("cooking_yields.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(String(500), default="")
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # manual | advisor | copy | saved_meal
    logged_entry_id: Mapped[int | None] = mapped_column(ForeignKey("log_entries.id", ondelete="SET NULL"))
    # Who added it, when that wasn't the plan's owner (someone they shared their plan with).
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanShare(Base):
    """One user letting another see, and optionally edit, their meal plan and shopping list."""

    __tablename__ = "plan_shares"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProfileShare(Base):
    """One user giving another access to all of their data (log, foods, recipes, plan, profile),
    to see or to see and change, as if signed in as them. Not their account or sharing settings."""

    __tablename__ = "profile_shares"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShoppingCheck(Base):
    """A ticked-off line on a shopping list (key identifies the list's date range and the item)."""

    __tablename__ = "shopping_checks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanProposal(Base):
    """Plan items suggested by the advisor; nothing is added to the plan until the user accepts."""

    __tablename__ = "plan_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("advisor_conversations.id", ondelete="CASCADE"))
    rationale: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | dismissed
    accepted_indexes: Mapped[list | None] = mapped_column(JSON)  # which items were added to the plan
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordReset(Base):
    """A one-time password reset / set-password token (only its hash is stored)."""

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
