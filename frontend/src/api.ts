import type {
  BarcodeResult,
  AccountUpdate,
  AdminUser,
  BodyInput,
  BodyMeasurement,
  Dataset,
  ImportJob,
  InviteResult,
  PlanDay,
  PlanItem,
  PlanItemInput,
  PlanItemUpdate,
  Proposal,
  ResetLink,
  RetentionProfiles,
  ShoppingList,
  Trends,
  AppInfo,
  CalculateInput,
  CopyInput,
  FormChoiceResult,
  FormRow,
  Integration,
  LogUpdate,
  SavedMeal,
  SavedMealInput,
  SettingRow,
  SettingValue,
  Suggestion,
  TestResult,
  Meal,
  ConversationDetail,
  Conversation,
  CookingYield,
  DaySummary,
  DerivedYield,
  Food,
  FoodInput,
  FoodSummary,
  LogEntry,
  LogInput,
  NutrientDef,
  Nutrition,
  Profile,
  RangeDay,
  Recipe,
  RecipeInput,
  SearchHit,
  Source,
  TargetsResponse,
  User,
  YieldInput,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

function describeDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: ValidationItem) => {
        const field = (d.loc ?? []).filter((p) => p !== "body").join(".");
        const msg = (d.msg ?? "invalid").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Could not reach the server", 0);
  }
  if (resp.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await resp.json();
  } catch {
    // non-JSON body (e.g. proxy error page)
  }
  if (!resp.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(describeDetail(detail, `Request failed (${resp.status})`), resp.status);
  }
  return data as T;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
const del = (path: string, body?: unknown) => request<void>("DELETE", path, body);

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const out = s.toString();
  return out ? `?${out}` : "";
};

export const api = {
  // auth
  me: () => get<User>("/api/auth/me"),
  login: (email: string, password: string) => post<User>("/api/auth/login", { email, password }),
  register: (email: string, password: string, display_name: string) =>
    post<User>("/api/auth/register", { email, password, display_name }),
  logout: () => post<void>("/api/auth/logout"),
  forgotPassword: (email: string) => post<{ email_enabled: boolean }>("/api/auth/forgot", { email }),
  resetPassword: (token: string, new_password: string) => post<User>("/api/auth/reset", { token, new_password }),
  appInfo: () => get<AppInfo>("/api/app-info"),

  // own account
  updateAccount: (a: AccountUpdate) => put<User>("/api/account", a),
  changePassword: (current_password: string, new_password: string) =>
    put<void>("/api/account/password", { current_password, new_password }),
  deleteAccount: (password: string) => del("/api/account", { password }),
  exportData: () => download("/api/account/export", "mealplan-export.json"),

  // admin settings
  adminSettings: () => get<SettingRow[]>("/api/admin/settings"),
  saveAdminSettings: (values: Record<string, SettingValue>) => put<SettingRow[]>("/api/admin/settings", { values }),
  testIntegration: (integration: Integration) => post<TestResult>(`/api/admin/settings/test/${integration}`),
  testEmail: () => post<TestResult>("/api/admin/settings/test-email"),

  // admin: reference datasets
  datasets: () => get<Dataset[]>("/api/admin/datasets"),
  importDataset: (key: string) => post<ImportJob>(`/api/admin/datasets/${key}/import`),
  job: (id: number) => get<ImportJob>(`/api/admin/jobs/${id}`),
  deriveYields: () => post<{ yields: number }>("/api/admin/derive-yields"),

  // admin: users
  adminUsers: () => get<AdminUser[]>("/api/admin/users"),
  inviteUser: (email: string, display_name: string) => post<InviteResult>("/api/admin/users", { email, display_name }),
  updateUser: (id: number, changes: { is_admin?: boolean; is_active?: boolean }) => patch<AdminUser>(`/api/admin/users/${id}`, changes),
  userResetLink: (id: number) => post<ResetLink>(`/api/admin/users/${id}/reset-link`),
  signOutUser: (id: number) => post<{ ok: boolean }>(`/api/admin/users/${id}/sign-out`),
  deleteUser: (id: number) => del(`/api/admin/users/${id}`),

  // profile
  profile: () => get<Profile>("/api/profile"),
  saveProfile: (p: Profile) => put<Profile>("/api/profile", p),
  targets: () => get<TargetsResponse>("/api/targets"),

  // foods
  nutrients: () => get<NutrientDef[]>("/api/nutrients"),
  foods: (q: string, opts: { kind?: string; mine?: boolean; limit?: number } = {}) =>
    get<FoodSummary[]>(`/api/foods${qs({ q, ...opts })}`),
  food: (id: number) => get<Food>(`/api/foods/${id}`),
  createFood: (f: FoodInput) => post<Food>("/api/foods", f),
  updateFood: (id: number, f: FoodInput) => put<Food>(`/api/foods/${id}`, f),
  copyFood: (id: number) => post<Food>(`/api/foods/${id}/copy`),
  deleteFood: (id: number) => del(`/api/foods/${id}`),
  foodForms: (id: number) => get<FormRow[]>(`/api/foods/${id}/forms`),
  setFoodForm: (id: number, component_name: string, option_key: string | null) =>
    put<FormChoiceResult>(`/api/foods/${id}/forms`, { component_name, option_key }),

  // sources
  sources: () => get<Source[]>("/api/sources"),
  lookupBarcode: (code: string) => get<BarcodeResult>(`/api/sources/barcode/${encodeURIComponent(code)}`),
  searchSource: (key: string, q: string) => get<SearchHit[]>(`/api/sources/${key}/search${qs({ q })}`),
  importFood: (key: string, source_id: string, name_hint?: string) =>
    post<Food>(`/api/sources/${key}/import`, { source_id, name_hint }),

  // yields / conversions
  yields: (foodId: number) => get<CookingYield[]>(`/api/foods/${foodId}/yields`),
  createYield: (y: YieldInput) => post<CookingYield>("/api/yields", y),
  deleteYield: (id: number) => del(`/api/yields/${id}`),
  retentionProfiles: (food_id: number, q = "") => get<RetentionProfiles>(`/api/retention-profiles${qs({ food_id, q })}`),
  deriveYield: (raw_food_id: number, cooked_food_id: number) =>
    post<DerivedYield>("/api/yields/derive", { raw_food_id, cooked_food_id }),
  calculate: (c: CalculateInput) => post<Nutrition>("/api/nutrition/calculate", c),

  // recipes
  recipes: () => get<Recipe[]>("/api/recipes"),
  recipe: (id: number) => get<Recipe>(`/api/recipes/${id}`),
  createRecipe: (r: RecipeInput) => post<Recipe>("/api/recipes", r),
  updateRecipe: (id: number, r: RecipeInput) => put<Recipe>(`/api/recipes/${id}`, r),
  deleteRecipe: (id: number) => del(`/api/recipes/${id}`),

  // log
  addLog: (e: LogInput) => post<LogEntry>("/api/log", e),
  updateLog: (id: number, changes: LogUpdate) => patch<LogEntry>(`/api/log/${id}`, changes),
  deleteLog: (id: number) => del(`/api/log/${id}`),
  copyLog: (c: CopyInput) => post<LogEntry[]>("/api/log/copy", c),
  suggestions: (meal: Meal | null, q = "", limit = 12) => get<Suggestion[]>(`/api/log/suggestions${qs({ meal, q, limit })}`),

  // saved meals
  savedMeals: () => get<SavedMeal[]>("/api/saved-meals"),
  updateSavedMeal: (id: number, m: SavedMealInput) => put<SavedMeal>(`/api/saved-meals/${id}`, m),
  deleteSavedMeal: (id: number) => del(`/api/saved-meals/${id}`),
  logSavedMeal: (id: number, body: { meal?: Meal | null; consumed_at?: string | null }) =>
    post<LogEntry[]>(`/api/saved-meals/${id}/log`, body),
  savedMealFromLog: (name: string, date: string, meal: Meal) => post<SavedMeal>("/api/saved-meals/from-log", { name, date, meal }),
  day: (day?: string) => get<DaySummary>(`/api/summary/day${qs({ day })}`),
  range: (days: number) => get<RangeDay[]>(`/api/summary/range${qs({ days })}`),

  // trends & body
  trends: (days: number) => get<Trends>(`/api/trends${qs({ days })}`),
  body: (start?: string, end?: string) => get<BodyMeasurement[]>(`/api/body${qs({ start, end })}`),
  putBody: (date: string, b: BodyInput) => put<BodyMeasurement>(`/api/body/${date}`, b),
  deleteBody: (date: string) => del(`/api/body/${date}`),

  // meal plan
  plan: (start: string, end: string) => get<PlanDay[]>(`/api/plan${qs({ start, end })}`),
  addPlanItem: (p: PlanItemInput) => post<PlanItem>("/api/plan", p),
  updatePlanItem: (id: number, changes: PlanItemUpdate) => patch<PlanItem>(`/api/plan/${id}`, changes),
  deletePlanItem: (id: number) => del(`/api/plan/${id}`),
  logPlanItem: (id: number) => post<LogEntry>(`/api/plan/${id}/log`),
  logPlanDay: (date: string, meal?: Meal | null) => post<LogEntry[]>("/api/plan/log-day", { date, meal: meal ?? null }),
  copyPlan: (from_start: string, from_end: string, to_start: string) =>
    post<{ copied: number }>("/api/plan/copy", { from_start, from_end, to_start }),
  planSavedMeal: (saved_meal_id: number, date: string, meal?: Meal | null) =>
    post<PlanItem[]>("/api/plan/from-saved-meal", { saved_meal_id, date, meal: meal ?? null }),
  shopping: (start: string, end: string) => get<ShoppingList>(`/api/plan/shopping${qs({ start, end })}`),
  checkShopping: (start: string, end: string, key: string, checked: boolean) =>
    put<void>("/api/plan/shopping/check", { start, end, key, checked }),

  // advisor
  conversations: () => get<Conversation[]>("/api/advisor/conversations"),
  conversation: (id: number) => get<ConversationDetail>(`/api/advisor/conversations/${id}`),
  deleteConversation: (id: number) => del(`/api/advisor/conversations/${id}`),
  chat: (message: string, conversation_id?: number | null) =>
    post<ConversationDetail>("/api/advisor/chat", { message, conversation_id: conversation_id ?? null }),
  acceptProposal: (id: number, indexes: number[] | null) => post<Proposal>(`/api/advisor/proposals/${id}/accept`, { indexes }),
  dismissProposal: (id: number) => post<Proposal>(`/api/advisor/proposals/${id}/dismiss`),
};

/** GET a file and hand it to the browser as a download (keeps the server's filename when given). */
async function download(path: string, fallbackName: string): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(path, { credentials: "same-origin" });
  } catch {
    throw new ApiError("Could not reach the server", 0);
  }
  if (!resp.ok) {
    let detail: unknown = null;
    try {
      detail = ((await resp.json()) as { detail?: unknown }).detail;
    } catch {
      // not JSON
    }
    throw new ApiError(describeDetail(detail, `Request failed (${resp.status})`), resp.status);
  }
  const name = /filename="?([^";]+)"?/.exec(resp.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
