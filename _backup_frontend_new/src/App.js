import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "@/App.css";
import { AuthProvider } from "@/context/AuthContext";
import { I18nProvider } from "@/context/I18nContext";
import { Toaster } from "@/components/ui/sonner";
import ProtectedRoute from "@/components/ProtectedRoute";
import AppLayout from "@/components/AppLayout";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import Assets from "@/pages/Assets";
import AssetDetail from "@/pages/AssetDetail";
import AssetForm from "@/pages/AssetForm";
import Categories from "@/pages/Categories";
import Locations from "@/pages/Locations";
import Reports from "@/pages/Reports";
import UsersPage from "@/pages/Users";

function App() {
  return (
    <div className="App">
      <I18nProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route
                element={
                  <ProtectedRoute>
                    <AppLayout />
                  </ProtectedRoute>
                }
              >
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/assets" element={<Assets />} />
                <Route path="/assets/new" element={<AssetForm />} />
                <Route path="/assets/:id" element={<AssetDetail />} />
                <Route path="/assets/:id/edit" element={<AssetForm />} />
                <Route path="/categories" element={<Categories />} />
                <Route path="/locations" element={<Locations />} />
                <Route path="/reports" element={<Reports />} />
                <Route
                  path="/users"
                  element={
                    <ProtectedRoute requireAdmin>
                      <UsersPage />
                    </ProtectedRoute>
                  }
                />
              </Route>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </BrowserRouter>
          <Toaster richColors position="top-right" />
        </AuthProvider>
      </I18nProvider>
    </div>
  );
}

export default App;
