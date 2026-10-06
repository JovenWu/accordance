import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useParams,
} from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ToastProvider } from "@/components/ui/toast";
import { useAuth } from "@/auth/auth-context";
import { AdminUserPage } from "@/pages/AdminUserPage";
import { AdminUsersPage } from "@/pages/AdminUsersPage";
import { ComparePage } from "@/pages/ComparePage";
import { HomePage } from "@/pages/HomePage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { ReportPage } from "@/pages/ReportPage";
import { RunPage } from "@/pages/RunPage";

function LegacyRunRedirect() {
  const { runId } = useParams<{ runId: string }>();
  return <Navigate to={`/runs/${runId}`} replace />;
}

export default function App() {
  const { isAdmin } = useAuth();
  return (
    <ErrorBoundary>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route element={<AppShell />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/reports/:reportId" element={<ReportPage />} />
              <Route
                path="/reports/:reportId/compare"
                element={<ComparePage />}
              />
              <Route
                path="/reports/:reportId/versions/:runId"
                element={<LegacyRunRedirect />}
              />
              <Route path="/runs/:id" element={<RunPage />} />
              <Route path="/runs/:id/live" element={<RunPage />} />
              <Route
                path="/admin"
                element={<Navigate to="/admin/users" replace />}
              />
              <Route
                path="/admin/users"
                element={isAdmin ? <AdminUsersPage /> : <Navigate to="/" replace />}
              />
              <Route
                path="/admin/users/:id"
                element={
                  isAdmin ? <AdminUserPage /> : <Navigate to="/" replace />
                }
              />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </ErrorBoundary>
  );
}
