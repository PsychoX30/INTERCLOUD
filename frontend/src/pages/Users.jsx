import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PencilSimple, Trash } from "@phosphor-icons/react";
import { api, formatApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

export default function UsersPage() {
  const { t } = useI18n();
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", role: "staff", password: "" });

  const { data, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api.get("/users")).data,
  });

  const openEdit = (u) => {
    setEditing(u);
    setForm({ name: u.name, role: u.role, password: "" });
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      const body = { name: form.name, role: form.role };
      if (form.password) body.password = form.password;
      await api.put(`/users/${editing.id}`, body);
      toast.success("Diperbarui");
      qc.invalidateQueries({ queryKey: ["users"] });
      setEditing(null);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    }
  };

  const remove = async (u) => {
    if (u.id === me.id) return toast.error("Tidak bisa menghapus diri sendiri");
    if (!window.confirm(`${t("common.confirmDelete")} — ${u.email}`)) return;
    try {
      await api.delete(`/users/${u.id}`);
      toast.success("Dihapus");
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    }
  };

  return (
    <div className="space-y-6" data-testid="users-page">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Admin</div>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          {t("users.title")}
        </h1>
      </div>

      <Card className="ring-hair border-0 shadow-none">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="dense-table w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-2 text-left">{t("common.name")}</th>
                  <th className="px-4 py-2 text-left">{t("common.email")}</th>
                  <th className="px-4 py-2 text-left">{t("users.role")}</th>
                  <th className="px-4 py-2 text-left">Created</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {isLoading && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400">{t("common.loading")}</td></tr>}
                {(data || []).map((u) => (
                  <tr key={u.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-slate-900">{u.name}</td>
                    <td className="px-4 py-2 text-slate-700">{u.email}</td>
                    <td className="px-4 py-2">
                      <Badge variant="outline" className={u.role === "admin" ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-50 text-slate-700"}>
                        {u.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-slate-600 tabular-nums">{formatDate(u.created_at)}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => openEdit(u)} className="h-8 w-8 p-0" data-testid={`user-edit-${u.id}`}>
                          <PencilSimple size={16} />
                        </Button>
                        {u.id !== me.id && (
                          <Button variant="ghost" size="sm" onClick={() => remove(u)} className="h-8 w-8 p-0 text-red-600 hover:bg-red-50" data-testid={`user-delete-${u.id}`}>
                            <Trash size={16} />
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("common.edit")} — {editing?.email}</DialogTitle>
          </DialogHeader>
          {editing && (
            <form onSubmit={submit} className="space-y-4" data-testid="user-edit-form">
              <div>
                <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                  {t("common.name")}
                </Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="h-10" required />
              </div>
              <div>
                <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                  {t("users.role")}
                </Label>
                <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                  <SelectTrigger className="h-10"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="staff">Staff</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                  {t("common.newPassword")} (opsional)
                </Label>
                <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="h-10" placeholder="Kosongkan untuk tidak mengubah" />
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setEditing(null)} className="rounded-full">
                  {t("common.cancel")}
                </Button>
                <Button type="submit" className="rounded-full bg-[#0F172A] hover:bg-[#1e293b]" data-testid="user-edit-submit">
                  {t("common.save")}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
