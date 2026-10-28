import { useCallback, useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useApp } from "@/context/AppContext";
import { Empty, Field, Loading, PageHeader, Sel, StatusBadge } from "@/components/common";
import TxDetail from "@/components/TxDetail";
import { num, usd, useApi } from "@/lib/api";

const STATUSES = ["draft", "pending_step1", "pending_special", "pending_step2", "approved", "posted", "rejected"];

const toCsv = (rows) => {
  const head = ["Ref", "Type", "Project", "Task", "Date", "Status", "Line", "Resource/Item", "Hour type", "Qty", "UOM", "Rate/Unit cost", "Cost", "Reason", "Submitted by"];
  const out = [head];
  rows.forEach((t) => t.lines.forEach((l, i) => out.push([t.ref, t.type, t.project_number, t.task_number, t.date, t.status, i + 1,
    l.resource_number || l.item_number, l.hour_type || "", l.hours ?? l.qty_consumed, l.uom || "hrs", l.rate ?? l.unit_cost, l.cost, l.reason_code || "", t.submitted_by])));
  return out.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
};

export default function Reports() {
  const api = useApi();
  const { master } = useApp();
  const [f, setF] = useState({ type: "", status: "", project_number: "" });
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState(null);
  const load = useCallback(async () => {
    const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v));
    setRows((await api.get("/transactions", { params })).data);
  }, [api, f]);
  useEffect(() => { load(); }, [load]);

  const summary = useMemo(() => {
    const m = {};
    (rows || []).filter((t) => !["draft", "rejected"].includes(t.status)).forEach((t) => {
      const k = `${t.project_number}|${t.task_number}`;
      m[k] = m[k] || { project: t.project_number, task: t.task_number, labor: 0, equipment: 0, material: 0 };
      m[k][t.type] += t.totals.cost;
    });
    return Object.values(m);
  }, [rows]);

  const download = () => {
    const blob = new Blob([toCsv(rows)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `costbridge-transactions-${new Date().toISOString().slice(0, 10)}.csv`; a.click();
  };
  const open = async (t) => setSel((await api.get(`/transactions/${t.id}`)).data);

  return (
    <div>
      <PageHeader eyebrow="Reports" title="Cost Transactions" desc="Every captured entry with its validation, approval chain and ERP status - the audit trail for cost-reimbursable billing and claims."
        actions={<Button variant="outline" onClick={download} disabled={!rows?.length} data-testid="reports-export-csv-btn"><Download className="mr-1.5 h-4 w-4" />Export CSV</Button>} />
      <div className="cb-card mb-6 grid gap-4 p-4 sm:grid-cols-3">
        <Field label="Type"><Sel data-testid="reports-type-filter" value={f.type} placeholder="All" onChange={(e) => setF({ ...f, type: e.target.value })}
          options={["labor", "equipment", "material"].map((t) => ({ value: t, label: t[0].toUpperCase() + t.slice(1) }))} /></Field>
        <Field label="Status"><Sel data-testid="reports-status-filter" value={f.status} placeholder="All" onChange={(e) => setF({ ...f, status: e.target.value })}
          options={STATUSES.map((s) => ({ value: s, label: s.replace("_", " ") }))} /></Field>
        <Field label="Project"><Sel data-testid="reports-project-filter" value={f.project_number} placeholder="All" onChange={(e) => setF({ ...f, project_number: e.target.value })}
          options={master.projects.map((p) => ({ value: p.number, label: p.number }))} /></Field>
      </div>
      {!rows ? <Loading /> : (
        <>
          <div className="cb-card mb-6 overflow-x-auto">
            <table className="w-full" data-testid="reports-summary-table">
              <thead><tr><th className="cb-th">Project / Task</th><th className="cb-th text-right">Labor</th><th className="cb-th text-right">Equipment</th><th className="cb-th text-right">Material</th><th className="cb-th text-right">Total</th></tr></thead>
              <tbody>{summary.map((s) => (
                <tr key={s.project + s.task} className="cb-row"><td className="cb-td">{s.project} / {s.task}</td>
                  <td className="cb-td num text-right">{usd(s.labor)}</td><td className="cb-td num text-right">{usd(s.equipment)}</td><td className="cb-td num text-right">{usd(s.material)}</td>
                  <td className="cb-td num text-right font-semibold">{usd(s.labor + s.equipment + s.material)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {rows.length === 0 ? <Empty>No transactions match.</Empty> : (
            <div className="cb-card overflow-x-auto">
              <table className="w-full" data-testid="reports-transactions-table">
                <thead><tr><th className="cb-th">Ref</th><th className="cb-th">Type</th><th className="cb-th">Project / Task</th><th className="cb-th">Date</th>
                  <th className="cb-th">Submitted by</th><th className="cb-th text-right">Qty</th><th className="cb-th text-right">Cost</th><th className="cb-th">Status</th></tr></thead>
                <tbody>{rows.map((t) => (
                  <tr key={t.id} className="cb-row cursor-pointer" onClick={() => open(t)} data-testid={`report-row-${t.ref}`}>
                    <td className="cb-td num text-xs">{t.ref}</td><td className="cb-td capitalize">{t.type}</td><td className="cb-td">{t.project_number} / {t.task_number}</td>
                    <td className="cb-td num text-xs">{t.date}</td><td className="cb-td">{t.submitted_by}</td>
                    <td className="cb-td num text-right">{num(t.totals?.qty, 2)} {t.totals?.uom}</td><td className="cb-td num text-right">{usd(t.totals?.cost)}</td>
                    <td className="cb-td"><StatusBadge status={t.status} /></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </>
      )}
      <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto border-white/10 bg-[#0B0F17] sm:max-w-3xl">
          <SheetHeader><SheetTitle className="font-display">Transaction detail</SheetTitle></SheetHeader>
          {sel && (
            <div className="mt-4 space-y-6">
              <TxDetail tx={sel} />
              <div>
                <div className="cb-eyebrow mb-2">ERP cost lines</div>
                {sel.cost_transactions.length === 0 ? <p className="text-sm text-muted-foreground">Created once the entry is fully approved.</p> :
                  sel.cost_transactions.map((c) => (
                    <div key={c.id} className="flex items-center justify-between border-t border-white/5 py-2 text-sm">
                      <span className="num text-xs">{c.ref} · {c.kind.replace(/_/g, " ")}</span><span className="num">{usd(c.amount)}</span><StatusBadge status={c.status} />
                    </div>
                  ))}
              </div>
              <div>
                <div className="cb-eyebrow mb-2">Audit trail</div>
                {sel.audit.map((a) => <div key={a.id} className="text-xs text-muted-foreground">{new Date(a.at).toLocaleString()} - {a.by}: {a.action}</div>)}
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
