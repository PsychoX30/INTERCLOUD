import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { Loader2 } from "lucide-react";

const CenterLoader = () => (
  <div className="min-h-screen flex items-center justify-center bg-slate-50">
    <Loader2 className="h-6 w-6 text-[#0a2350] animate-spin" />
  </div>
);

export const RequireAuth = ({ children, role }) => {
  const { user } = useAuth();
  if (user === undefined) return <CenterLoader />;
  if (!user) return <Navigate to="/portal/login" replace />;
  if (role) {
    const isStaff = ["admin", "sales", "support", "ticket_only"].includes(user.role);
    const allowed =
      role === "staff" ? isStaff :
      Array.isArray(role) ? role.includes(user.role) :
      user.role === role;
    if (!allowed) {
      const target = user.role === "client" ? "/portal/client/dashboard" : "/portal/admin/dashboard";
      return <Navigate to={target} replace />;
    }
  }
  return children;
};
