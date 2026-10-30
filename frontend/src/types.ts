// Mirrors backend/app/schemas.py and the dict-shaped responses in backend/app/routers.

export type Trust = "analytical" | "label" | "commercial" | "user" | "unverified";
export type Kind = "food" | "supplement";
export type FoodState = "raw" | "cooked" | "prepared";
export type Basis = "100g" | "serving";
export type WeighedState = "as_is" | "cooked";
export type Meal = "breakfast" | "lunch" | "dinner" | "snack" | "supplement";
export const MEALS: Meal[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];

export type NutrientMap = Record<string, number>;

export interface User {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
}

export type TargetBound = { min?: number | null; target?: number | null; max?: number | null };

export interface Profile {
  sex: "male" | "female" | null;
  birth_date: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  activity_level: "sedentary" | "light" | "moderate" | "active" | "very_active";
  goal: "lose" | "maintain" | "gain";
  life_stage: "none" | "pregnant" | "lactating";
  timezone: string | null; // null until the user picks one (server uses UTC meanwhile)
  health_notes: string;
  target_overrides: Record<string, TargetBound>;
}

export interface Target {
  min: number | null;
  target: number | null;
  max: number | null;
  kind: string;
  source: string;
  ul_scope: "total" | "supplemental" | null;
  note: string;
}

export interface TargetsResponse {
  targets: Record<string, Target>;
  warnings: string[];
}

export interface NutrientDef {
  code: string;
  name: string;
  unit: string;
  category: string;
}

export interface Portion {
  id: number;
  label: string;
  gram_weight: number;
}

export interface Component {
  name: string;
  amount: number | null;
  unit: string | null;
  note?: string | null;
}

export interface FoodSummary {
  id: number;
  name: string;
  brand: string | null;
  kind: Kind;
  state: FoodState | null;
  cooking_method: string | null;
  basis: Basis;
  serving_quantity: number | null;
  serving_unit: string | null;
  serving_size_g: number | null;
  source: string;
  source_data_type: string | null;
  trust_level: Trust;
  owner_id: number | null;
  macros: NutrientMap;
}

export interface Food extends FoodSummary {
  source_id: string | null;
  source_url: string | null;
  citation: string | null;
  fetched_at: string | null;
  created_at: string;
  nutrients: NutrientMap;
  derivations: Record<string, string | null>;
  portions: Portion[];
  other_components: Component[];
}

export interface FoodInput {
  name: string;
  brand: string | null;
  kind: Kind;
  state: FoodState | null;
  cooking_method: string | null;
  basis: Basis;
  serving_quantity: number | null;
  serving_unit: string | null;
  serving_size_g: number | null;
  citation: string | null;
  nutrients: NutrientMap;
  portions: { label: string; gram_weight: number }[];
  other_components: Component[];
}

export interface Source {
  key: string;
  name: string;
  description: string;
  homepage: string;
  trust_level: Trust;
  paid: boolean;
  enabled: boolean;
  disabled_reason: string | null;
}

export interface SearchHit {
  source: string;
  source_id: string;
  name: string;
  brand: string | null;
  kind: Kind;
  trust_level: Trust;
  basis: Basis;
  data_type: string | null;
  summary: NutrientMap;
  detail: string | null;
  imported_food_id: number | null;
}

export interface CookingYield {
  id: number;
  raw_food_id: number;
  cooked_food_id: number | null;
  method: string;
  yield_factor: number;
  retention: NutrientMap;
  basis: "measured" | "published" | "derived";
  trust_level: Trust;
  citation: string | null;
  notes: string | null;
  owner_id: number | null;
}

export interface YieldInput {
  raw_food_id: number;
  cooked_food_id?: number | null;
  method: string;
  yield_factor?: number | null;
  raw_weight_g?: number | null;
  cooked_weight_g?: number | null;
  retention?: NutrientMap;
  basis: "measured" | "published" | "derived";
  citation?: string | null;
  notes?: string | null;
}

export interface DerivedYield {
  yield_factor: number;
  dry_matter_check: number | null;
  trust_level: Trust;
  method_note: string;
}

export interface CalculateInput {
  food_id?: number | null;
  recipe_id?: number | null;
  quantity: number;
  unit: string;
  weighed_state?: WeighedState;
  yield_id?: number | null;
}

export interface Nutrition {
  nutrients: NutrientMap;
  grams: number | null;
  trust_level: Trust;
  other_components: Component[];
  notes: string[];
}

export interface IngredientInput {
  food_id: number;
  grams: number;
  weighed_state: WeighedState;
  yield_id: number | null;
  note: string;
}

export interface Ingredient extends IngredientInput {
  id: number;
  food_name: string;
}

export interface RecipeNutrition {
  total: NutrientMap;
  per_serving: NutrientMap;
  per_100g_cooked: NutrientMap | null;
  ingredient_mass_g: number;
  trust_level: Trust;
  other_components: Component[];
  ingredients: { id: number; food_id: number; grams: number | null; nutrients: NutrientMap; trust_level: Trust }[];
  notes: string[];
}

export interface Recipe {
  id: number;
  name: string;
  servings: number;
  cooked_weight_g: number | null;
  notes: string;
  ingredients: Ingredient[];
  nutrition: RecipeNutrition | { error: string } | null;
  updated_at: string;
}

export interface RecipeInput {
  name: string;
  servings: number;
  cooked_weight_g: number | null;
  notes: string;
  ingredients: IngredientInput[];
}

export interface LogInput extends CalculateInput {
  consumed_at?: string | null;
  meal: Meal;
  note?: string;
}

export interface LogEntry {
  id: number;
  consumed_at: string;
  meal: Meal;
  food_id: number | null;
  recipe_id: number | null;
  label: string;
  quantity: number;
  unit: string;
  weighed_state: WeighedState;
  yield_id: number | null;
  grams: number | null;
  is_supplement: boolean;
  nutrients: NutrientMap;
  other_components: Component[];
  trust_level: Trust;
  calc_notes: string[];
  note: string;
}

export interface Evaluation extends Target {
  code: string;
  amount: number;
  limit_amount: number;
  status: "ok" | "below" | "above_max";
}

export interface DaySummary {
  date: string;
  entries: LogEntry[];
  totals: NutrientMap;
  supplement_totals: NutrientMap;
  other_components: { name: string; unit: string; amount: number }[];
  evaluation: Evaluation[];
  warnings: string[];
  alerts: string[];
  energy_by_trust: Partial<Record<Trust, number>>;
}

export interface RangeDay {
  date: string;
  entries: number;
  totals: NutrientMap;
}

export interface Conversation {
  id: number;
  title: string;
  updated_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  tools_used: string[];
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}
