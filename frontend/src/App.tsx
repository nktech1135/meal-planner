import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Loading } from "./components/common";
import LoginPage from "./pages/Login";
import TodayPage from "./pages/Today";
import AddEntryPage from "./pages/AddEntry";
import FoodsPage from "./pages/Foods";
import FoodDetailPage from "./pages/FoodDetail";
import FoodFormPage from "./pages/FoodForm";
import RecipesPage from "./pages/Recipes";
import RecipeEditPage from "./pages/RecipeEdit";
import AdvisorPage from "./pages/Advisor";
import ProfilePage from "./pages/Profile";
import SettingsPage from "./pages/Settings";

const NAV = [
  { to: "/", label: "Today", end: true },
  { to: "/log", label: "Add" },
  { to: "/foods", label: "Foods" },
  { to: "/recipes", label: "Recipes" },
  { to: "/advisor", label: "Advisor" },
  { to: "/profile", label: "Profile" },
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
            {[...NAV, ...(user.is_admin ? [{ to: "/settings", label: "Settings", end: false }] : [])].map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <button type="button" className="btn-link" onClick={() => void logout()} title={user.email}>
            Sign out
          </button>
        </div>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/log" element={<AddEntryPage />} />
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
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
