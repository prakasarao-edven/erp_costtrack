import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useApp } from "@/context/AppContext";
import { Field, PageHeader, Sel } from "@/components/common";
import { errMsg, useApi } from "@/lib/api";

const Section = ({ title, desc, children }) => (
  <div className="cb-card p-5">
    <h3 className="text-base font-semibold md:text-lg">{title}</h3>
    {desc && <p className="mb-4 mt-1 text-xs text-muted-foreground">{desc}</p>}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
  </div>
);

const BEHAV = [{ value: "warning", label: "Warning (allow, flag)" }, { value: "stop", label: "Stopper (block submit)" }];

const Reasons = () => {
  const api = useApi();
  const { master, reloadMaster } = useApp();
  const [v, setV] = useState({ code: "", name: "", resource_type: "equipment" });
  const add = async () => { try { await api.post("/reason-codes", v); setV({ ...v, code: "", name: "" }); await reloadMaster(); toast.success("Reason code added"); } catch (e) { toast.error(errMsg(e)); } };
  const del = async (id) => { await api.delete(`/reason-codes/${id}`); await reloadMaster(); };
  return (
    <div className="cb-card p-5">
      <h3 className="mb-4 text-base font-semibold md:text-lg">Reason codes</h3>
      <table className="w-full" data-testid="reason-codes-table">
        <thead><tr><th className="cb-th">Code</th><th className="cb-th">Description</th><th className="cb-th">Applies to</th><th className="cb-th" /></tr></thead>
        <tbody>{master.reason_codes.map((r) => (
          <tr key={r.id} className="cb-row"><td className="cb-td num text-xs">{r.code}</td><td className="cb-td">{r.name}</td><td className="cb-td capitalize">{r.resource_type}</td>
            <td className="cb-td text-right"><button onClick={() => del(r.id)} className="text-muted-foreground hover:text-rose-400" data-testid={`reason-delete-${r.code}`}><Trash2 className="h-4 w-4" /></button></td></tr>
        ))}</tbody>
      </table>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <Field label="Code"><input className="cb-input w-32" value={v.code} onChange={(e) => setV({ ...v, code: e.target.value })} data-testid="reason-code-input" /></Field>
        <Field label="Description"><input className="cb-input w-64" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} data-testid="reason-name-input" /></Field>
        <Field label="Applies to"><Sel className="w-36" value={v.resource_type} onChange={(e) => setV({ ...v, resource_type: e.target.value })} options={[{ value: "equipment", label: "Equipment" }, { value: "material", label: "Material" }]} /></Field>
        <Button disabled={!v.code || !v.name} onClick={add} data-testid="reason-add-btn">Add</Button>
      </div>
    </div>
  );
};

export default function Setup() {
  const api = useApi();
  const { master, reloadMaster } = useApp();
  const [s, setS] = useState(() => JSON.parse(JSON.stringify(master.settings)));
  const [busy, setBusy] = useState(false);
  const up = (patch) => setS((x) => ({ ...x, ...patch }));
  const upO = (k, sub, val) => setS((x) => ({ ...x, oracle: { ...x.oracle, [k]: sub ? { ...x.oracle[k], [sub]: val } : val } }));
  const save = async () => {
    setBusy(true);
    try { const { _id, id, ...body } = s; await api.put("/settings", body); await reloadMaster(); toast.success("Setup saved"); }
    catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const toggleSpecial = (code, on) => up({ special_hour_types: on ? [...new Set([...s.special_hour_types, code])] : s.special_hour_types.filter((c) => c !== code) });

  return (
    <div>
      <PageHeader eyebrow="Setup / Configuration" title="Setup" desc="Per-deployment behavior - no code change needed. Applies to every new submission."
        actions={<Button onClick={save} disabled={busy} data-testid="setup-save-btn">Save setup</Button>} />
      <div className="space-y-6">
        <Section title="Budget check" desc="Cumulative actuals vs ERP task budget.">
          <Field label="Behavior"><Sel data-testid="setup-budget-behavior" value={s.budget_behavior} onChange={(e) => up({ budget_behavior: e.target.value })} options={BEHAV} /></Field>
          <Field label="Warning threshold (% of budget)"><input type="number" className="cb-input" data-testid="setup-budget-warning-pct" value={s.budget_warning_pct}
            onChange={(e) => up({ budget_warning_pct: Number(e.target.value) })} /></Field>
        </Section>
        <Section title="Plan tolerance" desc="Deviation (over or under) of actuals from planned hours / quantity.">
          {["labor", "equipment", "material"].map((t) => (
            <Field key={t} label={`${t} tolerance ±%`}><input type="number" className="cb-input" data-testid={`setup-tolerance-${t}`} value={s.tolerance_pct[t]}
              onChange={(e) => up({ tolerance_pct: { ...s.tolerance_pct, [t]: Number(e.target.value) } })} /></Field>
          ))}
          <Field label="Behavior"><Sel data-testid="setup-tolerance-behavior" value={s.tolerance_behavior} onChange={(e) => up({ tolerance_behavior: e.target.value })} options={BEHAV} /></Field>
        </Section>
        <Section title="Approvals" desc="Entries unmodified from a published plan (nobody unselected, no hours edited) can skip approval steps.">
          <Field label="Auto-approval scope"><Sel data-testid="setup-auto-approval" value={s.auto_approval} onChange={(e) => up({ auto_approval: e.target.value })}
            options={[{ value: "off", label: "Off - always 2-step" }, { value: "step1", label: "Skip Step 1 only (Cost Controller still reviews)" }, { value: "full", label: "Full skip (no approval)" }]} /></Field>
          <Field label="Special approver"><Sel data-testid="setup-special-approver" value={s.special_approver_role} onChange={(e) => up({ special_approver_role: e.target.value })}
            options={[{ value: "cost_controller", label: "Cost Controller" }, { value: "project_manager", label: "Project Manager" }, { value: "admin", label: "Admin" }]} /></Field>
          <div className="flex flex-col gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">Triggers special approval</span>
            {[["DOWN", "Equipment downtime"], ["MAINT", "Equipment maintenance"], ["IDLE", "Equipment idle"]].map(([c, l]) => (
              <label key={c} className="flex items-center gap-2 text-sm"><Switch checked={s.special_hour_types.includes(c)} onCheckedChange={(v) => toggleSpecial(c, v)} data-testid={`setup-special-${c}`} />{l}</label>
            ))}
            <label className="flex items-center gap-2 text-sm"><Switch checked={s.special_on_wastage} onCheckedChange={(v) => up({ special_on_wastage: v })} data-testid="setup-special-wastage" />Material wastage</label>
          </div>
        </Section>
        <Section title="Oracle cost import mapping" desc="Values sent on each Unprocessed Project Cost - must match the Transaction Source / Document / Document Entry configured in your Oracle tenant.">
          <Field label="Transaction source"><input className="cb-input" data-testid="setup-oracle-source" value={s.oracle.transaction_source} onChange={(e) => upO("transaction_source", null, e.target.value)} /></Field>
          {["labor", "equipment", "material"].map((t) => (
            <Field key={t} label={`${t} document / entry`}>
              <div className="flex gap-2">
                <input className="cb-input" value={s.oracle.document[t]} onChange={(e) => upO("document", t, e.target.value)} data-testid={`setup-oracle-doc-${t}`} />
                <input className="cb-input" value={s.oracle.document_entry[t]} onChange={(e) => upO("document_entry", t, e.target.value)} data-testid={`setup-oracle-entry-${t}`} />
              </div>
            </Field>
          ))}
        </Section>
        <Reasons />
      </div>
    </div>
  );
}
