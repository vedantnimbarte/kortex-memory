import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ScopeProvider } from "./lib/scope";
import { ToastProvider } from "./lib/toast";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Spinner } from "./components/ui";
import AppShell from "./components/AppShell";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import DashboardPage from "./pages/DashboardPage";
import RecallPage from "./pages/RecallPage";
import SearchPage from "./pages/SearchPage";
import MemoriesPage from "./pages/MemoriesPage";
import MemoryDetailPage from "./pages/MemoryDetailPage";
import ActivityPage from "./pages/ActivityPage";
import AttachmentsPage from "./pages/AttachmentsPage";
import IngestPage from "./pages/IngestPage";
import DataPage from "./pages/DataPage";
import KeysPage from "./pages/KeysPage";
import BillingPage from "./pages/BillingPage";
import SettingsPage from "./pages/SettingsPage";
import AdminPage from "./pages/AdminPage";

function FullScreen({ children }: { children: React.ReactNode }) {
  return <div className="grid min-h-screen place-items-center">{children}</div>;
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <FullScreen><Spinner /></FullScreen>;
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <FullScreen><Spinner /></FullScreen>;
  return user ? <Navigate to="/app" replace /> : <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
              <Route path="/signup" element={<PublicOnly><SignupPage /></PublicOnly>} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route
                path="/app"
                element={
                  <RequireAuth>
                    <ScopeProvider>
                      <AppShell />
                    </ScopeProvider>
                  </RequireAuth>
                }
              >
                <Route index element={<DashboardPage />} />
                <Route path="recall" element={<RecallPage />} />
                <Route path="search" element={<SearchPage />} />
                <Route path="memories" element={<MemoriesPage />} />
                <Route path="memories/:id" element={<MemoryDetailPage />} />
                <Route path="activity" element={<ActivityPage />} />
                <Route path="attachments" element={<AttachmentsPage />} />
                <Route path="ingest" element={<IngestPage />} />
                <Route path="data" element={<DataPage />} />
                <Route path="keys" element={<KeysPage />} />
                <Route path="billing" element={<BillingPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="admin" element={<AdminPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </ErrorBoundary>
  );
}
