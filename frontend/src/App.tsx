import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Loading } from "./components/common";
import { MeMenu } from "./components/MeMenu";
import LoginPage from "./pages/Login";
import ResetPasswordPage from "./pages/ResetPassword";
import TodayPage from "./pages/Today";
import AddEntryPage from "./pages/AddEntry";
import PlanPage from "./pages/Plan";
import ShoppingPage from "./pages/Shopping";
import TrendsPage from "./pages/Trends";
import FoodsPage from "./pages/Foods";
import FoodDetailPage from "./pages/FoodDetail";
import FoodFormPage from "./pages/FoodForm";
import RecipesPage from "./pages/Recipes";
import RecipeEditPage from "./pages/RecipeEdit";
import AdvisorPage from "./pages/Advisor";
import ProfilePage from "./pages/Profile";
import AccountPage from "./pages/Account";
import SettingsPage from "./pages/Settings";
import AdminDataPage from "./pages/AdminData";
import AdminUsersPage from "./pages/AdminUsers";

const NAV = [
  { to: "/", label: "Today", end: true },
  { to: "/log", label: "Add" },
  { to: "/plan", label: "Plan" },
  { to: "/trends", label: "Trends" },
  { to: "/foods", label: "Foods" },
  { to: "/recipes", label: "Recipes" },
  { to: "/advisor", label: "Advisor" },
];

export default function App() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <main className="container">
        <Loading />
      </main>
    );
  }
  if (!user) {
    return (
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">Mealplan</span>
          <nav className="nav" aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <MeMenu user={user} onSignOut={() => void logout()} />
        </div>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/log" element={<AddEntryPage />} />
          <Route path="/plan" element={<PlanPage />} />
          <Route path="/plan/shopping" element={<ShoppingPage />} />
          <Route path="/trends" element={<TrendsPage />} />
          <Route path="/foods" element={<FoodsPage />} />
          <Route path="/foods/new" element={<FoodFormPage />} />
          <Route path="/foods/:id" element={<FoodDetailPage />} />
          <Route path="/foods/:id/edit" element={<FoodFormPage />} />
          <Route path="/recipes" element={<RecipesPage />} />
          <Route path="/recipes/new" element={<RecipeEditPage />} />
          <Route path="/recipes/:id" element={<RecipeEditPage />} />
          <Route path="/advisor" element={<AdvisorPage />} />
          <Route path="/advisor/:id" element={<AdvisorPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/data" element={<AdminDataPage />} />
          <Route path="/settings/users" element={<AdminUsersPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
