import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { RequireAuth, RequireGuest } from "@/components/route-guards";

// Route-level code splitting. The landing page is its own chunk, so a visitor
// who never logs in downloads neither the app shell nor the auth screens.
const LandingPage = lazy(() => import("./routes/landing"));
const LoginPage = lazy(() => import("./routes/login"));
const SignupPage = lazy(() => import("./routes/signup"));
const HomePage = lazy(() => import("./routes/home"));

export default function App() {
  return (
    <Suspense fallback={null}>
      <Routes>
        {/* Public. Renders for logged-in users too -- it just swaps its CTA
            for "Open Dendrite" rather than bouncing them away from it. */}
        <Route path="/" element={<LandingPage />} />

        <Route element={<RequireGuest />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route path="/app" element={<HomePage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
