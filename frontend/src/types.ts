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
  pinned_nutrients: string[]; // nutrient codes always shown on Today
  unit_system: UnitSystem;
}

export type UnitSystem = "metric" | "imperial";

export interface Target {
  min: number | null;
  target: number | null;
  max: number | null;
  kind: string;
  source: string;
  ul_scope: "total" | "supplemental" | null;
  note: string;
  /** true: max is a safety/health limit (UL, CDRR, DGA cap); false: top of a macronutrient range. */
  max_is_limit?: boolean;
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
  category: string | null; // e.g. USDA food group "Vegetables and Vegetable Products"
  trust_level: Trust;
  owner_id: number | null;
  macros: NutrientMap;
  barcode?: string | null;
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
  ingredients?: string | null;
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
  barcode?: string | null;
  ingredients?: string | null;
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
  generated_by: string | null; // "usda-pairs": derived automatically from USDA raw/cooked entries
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
  retention_profile_code?: number | null; // USDA retention table profile; fills `retention` server-side
  basis: "measured" | "published" | "derived";
  citation?: string | null;
  notes?: string | null;
}

export interface RetentionProfile {
  code: number;
  description: string;
  food_group: string | null;
  factors: NutrientMap; // nutrient code -> fraction retained
  release: string;
}

export interface RetentionProfiles {
  food_group: string | null; // the raw food's group the list was narrowed to, if known
  profiles: RetentionProfile[];
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

/** A label amount that couldn't be counted toward a nutrient (e.g. vitamin A in IU of unknown form). */
export interface Uncounted {
  name: string;
  amount: number;
  unit: string | null;
  item: string;
  entry_id: number;
  food_id: number | null;
  resolvable: boolean; // the user can pick the chemical form on the food page
}

export type EvaluationStatus = "ok" | "below" | "above_max" | "above_range" | "partial";

export interface Evaluation extends Target {
  code: string;
  amount: number;
  limit_amount: number;
  status: EvaluationStatus;
  uncounted: Uncounted[];
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

export interface ChatSource {
  url: string;
  title: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  tools_used: string[];
  sources: ChatSource[];
  created_at: string;
}

export interface ProposalItem {
  date: string;
  meal: Meal;
  food_id: number | null;
  recipe_id: number | null;
  quantity: number;
  unit: string;
  label: string;
  weighed_state?: WeighedState;
  yield_id?: number | null;
  note?: string;
}

export interface Proposal {
  id: number;
  rationale: string;
  items: ProposalItem[];
  status: "pending" | "accepted" | "dismissed";
  created_at: string;
  accepted_indexes?: number[] | null;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
  proposals: Proposal[];
}

export interface LogUpdate {
  consumed_at?: string;
  meal?: Meal;
  quantity?: number;
  unit?: string;
  weighed_state?: WeighedState;
  yield_id?: number | null;
  note?: string;
}

export interface CopyInput {
  from_date: string;
  to_date: string;
  meal?: Meal | null;
  to_meal?: Meal | null;
}

export interface Suggestion {
  food_id: number | null;
  recipe_id: number | null;
  label: string;
  kind: Kind | "recipe";
  trust_level: Trust;
  quantity: number;
  unit: string;
  weighed_state: WeighedState;
  yield_id: number | null;
  meal: Meal;
  times: number;
  last_used: string;
  energy_kcal: number | null;
}

export interface SavedMealItemInput {
  food_id: number | null;
  recipe_id: number | null;
  quantity: number;
  unit: string;
  weighed_state: WeighedState;
  yield_id: number | null;
}

export interface SavedMealItem extends SavedMealItemInput {
  id: number;
  label: string;
}

export interface SavedMealInput {
  name: string;
  default_meal: Meal;
  items: SavedMealItemInput[];
}

export interface SavedMeal {
  id: number;
  name: string;
  default_meal: Meal;
  items: SavedMealItem[];
}

// --- supplement form choices --------------------------------------------------

export interface FormOption {
  key: string;
  label: string;
  factor: number;
  result: number;
  unit: string;
  note: string;
  source: string;
}

export interface FormRow {
  component_name: string;
  amount: number;
  unit: string | null;
  nutrient_code: string;
  nutrient_name: string;
  chosen: string | null;
  options: FormOption[];
}

export interface FormChoiceResult {
  forms: FormRow[];
  recalculated_entries: number;
}

// --- app settings (admin) -------------------------------------------------------

export interface AppInfo {
  allow_registration: boolean;
  advisor_configured: boolean;
  usda_demo_key: boolean;
  email_enabled: boolean;
}

export type SettingKind = "secret" | "string" | "bool" | "int" | "choice";
export type SettingValue = string | number | boolean | null;

export interface SettingRow {
  key: string;
  label: string;
  group: string;
  kind: SettingKind;
  description: string;
  choices: string[];
  minimum: number | null;
  maximum: number | null;
  link: string | null;
  value: SettingValue; // secrets come back masked, e.g. "••••••••WXYZ"
  is_set: boolean;
  source: "settings" | "environment" | "default";
}

export type Integration = "anthropic" | "usda_fdc" | "nutritionix" | "edamam";

export interface TestResult {
  ok: boolean;
  message: string;
}

// --- reference datasets (admin) ---------------------------------------------------

export type JobStatus = "queued" | "running" | "done" | "failed";

export interface ImportJob {
  id: number;
  dataset: string;
  release: string | null;
  status: JobStatus;
  progress: number;
  total: number | null;
  message: string;
  created_at: string;
  finished_at: string | null;
}

export interface Dataset {
  key: string;
  label: string;
  description: string;
  size: string;
  available_release: string | null;
  imported_release: string | null;
  update_available: boolean;
  records: number;
  last_job: ImportJob | null;
}

// --- users (admin) and the signed-in account -------------------------------------

export interface AdminUser {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  log_entries: number;
}

export interface InviteResult {
  user: AdminUser;
  link: string;
  emailed: boolean;
}

export interface ResetLink {
  link: string;
  expires_in_hours: number;
}

export interface AccountUpdate {
  display_name: string;
  email: string;
  current_password?: string | null;
}

// --- trends & body measurements ---------------------------------------------------

export interface BodyMeasurement {
  date: string;
  weight_kg: number | null;
  body_fat_pct: number | null;
  waist_cm: number | null;
  note: string;
}

export type BodyInput = Omit<BodyMeasurement, "date">;

export interface TrendEvaluation extends Evaluation {
  days_ok: number; // logged days on which this nutrient was on target
}

export interface WeightPoint {
  date: string;
  weight_kg: number;
  trend_kg: number;
}

export interface EnergyEstimate {
  available: boolean;
  reason?: string;
  maintenance_kcal?: number;
  average_intake_kcal?: number;
  trend_change_kg?: number;
  days?: number;
  logged_fraction?: number;
  method: string;
}

export interface TrendDay {
  date: string;
  logged: boolean;
  totals: NutrientMap;
}

export interface Trends {
  start: string;
  end: string;
  days: number;
  logged_days: number;
  daily: TrendDay[];
  averages: NutrientMap;
  evaluation: TrendEvaluation[];
  weight: WeightPoint[];
  body: Omit<BodyMeasurement, "note">[];
  energy_estimate: EnergyEstimate;
  warnings: string[];
}

// --- meal plan --------------------------------------------------------------------

export type PlanOrigin = "manual" | "advisor" | "copy" | "saved_meal";

export interface PlanItemInput {
  date: string;
  meal: Meal;
  food_id?: number | null;
  recipe_id?: number | null;
  quantity: number;
  unit: string;
  weighed_state?: WeighedState;
  yield_id?: number | null;
  note?: string;
}

export interface PlanItemUpdate {
  date?: string;
  meal?: Meal;
  quantity?: number;
  unit?: string;
  weighed_state?: WeighedState;
  yield_id?: number | null;
  note?: string;
}

export interface PlanItem {
  id: number;
  date: string;
  meal: Meal;
  position: number;
  label: string;
  quantity: number;
  unit: string;
  weighed_state: WeighedState;
  yield_id: number | null;
  food_id: number | null;
  recipe_id: number | null;
  note: string;
  origin: PlanOrigin;
  logged_entry_id: number | null;
  nutrients: NutrientMap;
  trust_level: Trust | null;
  grams: number | null;
  error: string | null;
}

export interface PlanDay {
  date: string;
  items: PlanItem[];
  totals: NutrientMap;
  evaluation: Evaluation[];
}

export interface ShoppingItem {
  key: string;
  food_id: number;
  name: string;
  brand: string | null;
  category: string;
  unit: string;
  amount: number;
  used_for: string[];
  checked: boolean;
}

export interface ShoppingList {
  start: string;
  end: string;
  items: ShoppingItem[];
}

export interface BarcodeResult {
  barcode: string;
  found_in: "local" | "usda_fdc" | "open_food_facts" | null;
  foods: FoodSummary[];
  errors: string[];
}
