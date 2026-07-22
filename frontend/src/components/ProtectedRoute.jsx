import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function ProtectedRoute({ children, requireAdmin = false }) {
  const { user } = useAuth();
  if (user === null) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-slate-500">
        Memuat sesi…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (requireAdmin && user.role !== "admin") return <Navigate to="/dashboard" replace />;
  return children;
}
