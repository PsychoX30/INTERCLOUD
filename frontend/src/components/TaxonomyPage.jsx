import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, PencilSimple, Trash } from "@phosphor-icons/react";
import { api, formatApiError } from "@/lib/api";
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
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

/**
 * Generic taxonomy CRUD used by Categories & Locations pages.
 * `resource`: "categories" | "locations"
 * `extraField`: "description" | "address"
 */
export default function TaxonomyPage({ resource, title, extraField, extraLabel }) {
  const { t } = useI18n();
  const { user } = useAuth();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", code: "", [extraField]: "" });

  const { data, isLoading } = useQuery({
    queryKey: [resource],
    queryFn: async () => (await api.get(`/${resource}`)).data,
  });

  const openNew = () => {
    setEditing(null);
    setForm({ name: "", code: "", [extraField]: "" });
    setOpen(true);
  };
  const openEdit = (row) => {
    setEditing(row);
    setForm({ name: row.name, code: row.code || "", [extraField]: row[extraField] || "" });
    setOpen(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      if (editing) await api.put(`/${resource}/${editing.id}`, form);
      else await api.post(`/${resource}`, form);
      toast.success("Tersimpan");
      qc.invalidateQueries({ queryKey: [resource] });
      setOpen(false);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    }
  };

  const remove = async (row) => {
    if (!window.confirm(`${t("common.confirmDelete")} — ${row.name}`)) return;
    try {
      await api.delete(`/${resource}/${row.id}`);
      toast.success("Dihapus");
      qc.invalidateQueries({ queryKey: [resource] });
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    }
  };

  return (
    <div className="space-y-6" data-testid={`${resource}-page`}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Master</div>
          <h1 className="mt-1 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            {title}
          </h1>
        </div>
        {isAdmin && (
          <Button
            onClick={openNew}
            className="h-10 gap-2 rounded-full bg-[#0F172A] px-5 hover:bg-[#1e293b]"
            data-testid={`${resource}-new-button`}
          >
            <Plus size={16} /> {t("common.create")}
          </Button>
        )}
      </div>

      <Card className="ring-hair border-0 shadow-none">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="dense-table w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-2 text-left">{t("common.name")}</th>
                  <th className="px-4 py-2 text-left">{t("common.code")}</th>
                  <th className="px-4 py-2 text-left">{extraLabel}</th>
                  {isAdmin && <th className="px-4 py-2"></th>}
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">{t("common.loading")}</td></tr>
                )}
                {!isLoading && (data || []).length === 0 && (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">{t("common.empty")}</td></tr>
                )}
                {(data || []).map((row) => (
                  <tr key={row.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-slate-900">{row.name}</td>
                    <td className="px-4 py-2 font-mono text-xs text-slate-600">{row.code || "—"}</td>
                    <td className="px-4 py-2 text-slate-700">{row[extraField] || "—"}</td>
                    {isAdmin && (
                      <td className="px-4 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => openEdit(row)} className="h-8 w-8 p-0" data-testid={`${resource}-edit-${row.id}`}>
                            <PencilSimple size={16} />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => remove(row)} className="h-8 w-8 p-0 text-red-600 hover:bg-red-50" data-testid={`${resource}-delete-${row.id}`}>
                            <Trash size={16} />
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t("common.edit") : t("common.create")} — {title}</DialogTitle>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-4" data-testid={`${resource}-form`}>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.name")}
              </Label>
              <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="h-10" data-testid={`${resource}-name-input`} />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.code")}
              </Label>
              <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} className="h-10" data-testid={`${resource}-code-input`} />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {extraLabel}
              </Label>
              <Textarea rows={3} value={form[extraField]} onChange={(e) => setForm({ ...form, [extraField]: e.target.value })} data-testid={`${resource}-extra-input`} />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)} className="rounded-full">
                {t("common.cancel")}
              </Button>
              <Button type="submit" className="rounded-full bg-[#0F172A] hover:bg-[#1e293b]" data-testid={`${resource}-submit`}>
                {t("common.save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
