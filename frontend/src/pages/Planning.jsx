import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApp } from "@/context/AppContext";
import { Field, PageHeader, ProjectTaskFields, Sel, StatusBadge } from "@/components/common";
import { errMsg, today, usd, useApi } from "@/lib/api";
import NewCrewDialog from "@/components/NewCrewDialog";

const SHIFTS = ["Day Shift (06:00-14:00)", "Evening Shift (14:00-22:00)", "Night Shift (22:00-06:00)"];
const COLS = [["REG", "Regular"], ["OT", "OT"], ["IDLE", "Idle"], ["HW", "Harsh Weather"], ["MAINT", "Maintenance"], ["DOWN", "Downtime"]];

const blank = (kind) => ({ kind, project_number: "", task_number: "", crew_id: "", shift: SHIFTS[0], period_type: "monthly",
  start_date: today(), end_date: today(), lines: [] });

const PlanList = ({ plans, onOpen, crews, activeId }) => (
  <div className="cb-card divide-y divide-white/5" data-testid="plan-list">
    {plans.length === 0 && <div className="p-4 text-sm text-muted-foreground">No plans yet.</div>}
    {plans.map((p) => (
      <button key={p.id} onClick={() => onOpen(p)} data-testid={`plan-list-item-${p.id}`}
        className={`block w-full px-4 py-3 text-left transition-colors hover:bg-white/[0.03] ${activeId === p.id ? "bg-amber-500/5" : ""}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">{p.project_number} / {p.task_number}</span><StatusBadge status={p.status} />
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {p.kind === "crew" ? `${crews.find((c) => c.id === p.crew_id)?.name || "-"} · ${p.shift}` : `${p.period_type}`} · {p.start_date} to {p.end_date}
        </div>
      </button>
    ))}
  </div>
);

const CrewGrid = ({ plan, setPlan, master }) => {
  const htFor = (rt) => master.hour_types.filter((h) => h.resource_type === rt).map((h) => h.code);
  const setLine = (i, patch) => setPlan((p) => ({ ...p, lines: p.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  return (
    <div className="cb-card overflow-x-auto">
      <table className="w-full" data-testid="crew-plan-grid">
        <thead><tr><th className="cb-th">Resource / Equipment</th>{COLS.map(([c, l]) => <th key={c} className="cb-th text-right">{l}</th>)}<th className="cb-th" /></tr></thead>
        <tbody>
          {plan.lines.length === 0 && <tr><td colSpan={8} className="p-6 text-center text-sm text-muted-foreground">Add employees and equipment to this crew plan.</td></tr>}
          {plan.lines.map((ln, i) => {
            const allowed = htFor(ln.resource_type);
            const opts = (ln.resource_type === "labor" ? master.employees : master.equipment).map((r) => ({ value: r.number, label: `${r.number} - ${r.name}` }));
            return (
              <tr key={i} className="cb-row">
                <td className="cb-td min-w-[230px]">
                  <div className="flex gap-2">
                    <Sel className="w-28" data-testid={`plan-line-${i}-type-select`} value={ln.resource_type} onChange={(e) => setLine(i, { resource_type: e.target.value, resource_number: "", hours: {} })}
                      options={[{ value: "labor", label: "Labor" }, { value: "equipment", label: "Equip." }]} />
                    <Sel data-testid={`plan-line-${i}-resource-select`} value={ln.resource_number} placeholder="Select" onChange={(e) => setLine(i, { resource_number: e.target.value })} options={opts} />
                  </div>
                </td>
                {COLS.map(([c]) => (
                  <td key={c} className="cb-td w-24">
                    {allowed.includes(c) ? (
                      <input type="number" min="0" max="24" step="0.5" className="cb-input num text-right" data-testid={`plan-line-${i}-hours-${c}`}
                        value={ln.hours[c] ?? ""} onChange={(e) => setLine(i, { hours: { ...ln.hours, [c]: e.target.value === "" ? undefined : Number(e.target.value) } })} />
                    ) : <span className="block text-center text-muted-foreground">-</span>}
                  </td>
                ))}
                <td className="cb-td"><button onClick={() => setPlan((p) => ({ ...p, lines: p.lines.filter((_, j) => j !== i) }))} data-testid={`plan-line-${i}-remove-btn`}
                  className="text-muted-foreground hover:text-rose-400"><Trash2 className="h-4 w-4" /></button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const MaterialGrid = ({ plan, setPlan, master }) => {
  const setLine = (i, patch) => setPlan((p) => ({ ...p, lines: p.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  const total = plan.lines.reduce((s, l) => s + (l.planned_qty || 0) * (master.items.find((x) => x.number === l.item_number)?.unit_cost || 0), 0);
  return (
    <div className="cb-card overflow-x-auto">
      <table className="w-full" data-testid="material-plan-grid">
        <thead><tr><th className="cb-th">Item</th><th className="cb-th">UOM</th><th className="cb-th text-right">Unit cost (ERP)</th>
          <th className="cb-th text-right">Planned qty</th><th className="cb-th text-right">Planned cost</th><th className="cb-th" /></tr></thead>
        <tbody>
          {plan.lines.map((ln, i) => {
            const it = master.items.find((x) => x.number === ln.item_number);
            return (
              <tr key={i} className="cb-row">
                <td className="cb-td min-w-[240px]"><Sel data-testid={`mplan-line-${i}-item-select`} value={ln.item_number || ""} placeholder="Select item"
                  onChange={(e) => setLine(i, { item_number: e.target.value })} options={master.items.map((x) => ({ value: x.number, label: `${x.number} - ${x.description}` }))} /></td>
                <td className="cb-td text-xs">{it?.uom || "-"}</td>
                <td className="cb-td num text-right">{it ? usd(it.unit_cost) : "-"}</td>
                <td className="cb-td w-32"><input type="number" min="0" className="cb-input num text-right" data-testid={`mplan-line-${i}-qty-input`} value={ln.planned_qty ?? ""}
                  onChange={(e) => setLine(i, { planned_qty: e.target.value === "" ? null : Number(e.target.value) })} /></td>
                <td className="cb-td num text-right">{it ? usd((ln.planned_qty || 0) * it.unit_cost) : "-"}</td>
                <td className="cb-td"><button onClick={() => setPlan((p) => ({ ...p, lines: p.lines.filter((_, j) => j !== i) }))} className="text-muted-foreground hover:text-rose-400"><Trash2 className="h-4 w-4" /></button></td>
              </tr>
            );
          })}
          <tr className="border-t border-white/10"><td colSpan={4} className="cb-td text-right text-muted-foreground">Total planned cost</td>
            <td className="cb-td num text-right font-semibold" data-testid="material-plan-total">{usd(total)}</td><td /></tr>
        </tbody>
      </table>
    </div>
  );
};

const Editor = ({ kind, plan, setPlan, onSaved, onNew }) => {
  const api = useApi();
  const { master, reloadMaster } = useApp();
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    try { await api.delete(`/plans/${plan.id}`); toast.success("Draft plan deleted"); onNew(); onSaved(); } catch (e) { toast.error(errMsg(e)); }
  };
  const crews = master.crews.filter((c) => !plan.project_number || c.project_number === plan.project_number);
  const save = async (publish) => {
    setBusy(true);
    try {
      const body = { ...plan, crew_id: plan.crew_id || null, lines: plan.lines.map((l) => (kind === "crew"
        ? { resource_type: l.resource_type, resource_number: l.resource_number, hours: Object.fromEntries(Object.entries(l.hours).filter(([, v]) => v !== undefined && v !== null)) }
        : { item_number: l.item_number, planned_qty: l.planned_qty })) };
      let { data } = plan.id ? await api.put(`/plans/${plan.id}`, body) : await api.post("/plans", body);
      if (publish) data = (await api.post(`/plans/${data.id}/publish`)).data;
      toast.success(publish ? "Plan published - it now drives timesheet auto-fill" : "Draft saved");
      setPlan(data); onSaved();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const addLine = () => setPlan((p) => ({ ...p, lines: [...p.lines, kind === "crew" ? { resource_type: "labor", resource_number: "", hours: { REG: 8 } } : { item_number: "", planned_qty: null }] }));
  return (
    <div className="space-y-4">
      <div className="cb-card grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
        <ProjectTaskFields testid={`${kind}-plan`} value={plan} onChange={(p) => setPlan((x) => ({ ...x, ...p }))} />
        {kind === "crew" ? (
          <>
            <Field label="Crew / Team">
              <div className="flex gap-2">
                <Sel data-testid="crew-plan-crew-select" value={plan.crew_id || ""} placeholder="Select crew" onChange={(e) => setPlan((x) => ({ ...x, crew_id: e.target.value }))}
                  options={crews.map((c) => ({ value: c.id, label: c.name }))} />
                <NewCrewDialog projectNumber={plan.project_number} onCreated={async (c) => { await reloadMaster(); setPlan((x) => ({ ...x, crew_id: c.id })); }} />
              </div>
            </Field>
            <Field label="Shift"><Sel data-testid="crew-plan-shift-select" value={plan.shift} onChange={(e) => setPlan((x) => ({ ...x, shift: e.target.value }))} options={SHIFTS.map((s) => ({ value: s, label: s }))} /></Field>
          </>
        ) : (
          <Field label="Period"><Sel data-testid="material-plan-period-select" value={plan.period_type} onChange={(e) => setPlan((x) => ({ ...x, period_type: e.target.value }))}
            options={[{ value: "weekly", label: "Weekly" }, { value: "monthly", label: "Monthly" }]} /></Field>
        )}
        <Field label="Start date"><input type="date" className="cb-input" data-testid={`${kind}-plan-start-input`} value={plan.start_date} onChange={(e) => setPlan((x) => ({ ...x, start_date: e.target.value }))} /></Field>
        <Field label="End date"><input type="date" className="cb-input" data-testid={`${kind}-plan-end-input`} value={plan.end_date} onChange={(e) => setPlan((x) => ({ ...x, end_date: e.target.value }))} /></Field>
      </div>
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold md:text-lg">{kind === "crew" ? "Assigned resources - planned hours by hour type / day" : "Planned consumption for the period"}</h3>
        <Button size="sm" variant="ghost" onClick={addLine} data-testid={`${kind}-plan-add-line-btn`}><Plus className="mr-1 h-4 w-4" />{kind === "crew" ? "Add resource / equipment" : "Add item"}</Button>
      </div>
      {kind === "crew" ? <CrewGrid plan={plan} setPlan={setPlan} master={master} /> : <MaterialGrid plan={plan} setPlan={setPlan} master={master} />}
      <p className="text-xs text-muted-foreground">
        {kind === "crew" ? "Planned hours apply to each day in the range - same hour-type taxonomy as Rate Cards and Timesheets. Publishing checks that no resource is double-booked on the same shift." :
          "Unit cost always comes from the ERP item master. Issues during this period are checked against planned quantity using the tolerance from Setup."}
      </p>
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" disabled={busy} onClick={() => save(false)} data-testid={`${kind}-plan-save-draft-btn`}>Save draft</Button>
        <Button disabled={busy} onClick={() => save(true)} data-testid={`${kind}-plan-publish-btn`}>Publish plan</Button>
        <Button variant="ghost" onClick={onNew} data-testid={`${kind}-plan-new-btn`}>New plan</Button>
        {plan.id && plan.status === "draft" && (
          <Button variant="ghost" className="text-rose-400" onClick={remove} data-testid={`${kind}-plan-delete-btn`}><Trash2 className="mr-1 h-4 w-4" />Delete draft</Button>
        )}
        {plan.status && <StatusBadge status={plan.status} testid={`${kind}-plan-status`} />}
      </div>
    </div>
  );
};

const PlanTab = ({ kind }) => {
  const api = useApi();
  const { master } = useApp();
  const [plans, setPlans] = useState([]);
  const [plan, setPlan] = useState(blank(kind));
  const load = useCallback(async () => setPlans((await api.get("/plans", { params: { kind } })).data), [api, kind]);
  useEffect(() => { load(); }, [load]);
  const open = (p) => setPlan({ ...blank(kind), ...p, crew_id: p.crew_id || "", lines: p.lines.map((l) => ({ ...l, hours: { ...(l.hours || {}) } })) });
  return (
    <div className="grid gap-6 xl:grid-cols-[300px_1fr]">
      <div><div className="cb-eyebrow mb-2">Plans</div><PlanList plans={plans} onOpen={open} crews={master.crews} activeId={plan.id} /></div>
      <Editor kind={kind} plan={plan} setPlan={setPlan} onSaved={load} onNew={() => setPlan(blank(kind))} />
    </div>
  );
};

export default function Planning() {
  const { me } = useApp();
  const crewAllowed = me.role !== "store_manager";
  return (
    <div>
      <PageHeader eyebrow="Planning" title="Crew & Material Planning" desc="Assign employees and equipment to a crew against Project# / Task# for a date range and shift. Published plans auto-fill the timesheets." />
      <Tabs defaultValue={crewAllowed ? "crew" : "material"}>
        <TabsList className="mb-6">
          {crewAllowed && <TabsTrigger value="crew" data-testid="planning-tab-crew">Crew plan (Labor & Equipment)</TabsTrigger>}
          <TabsTrigger value="material" data-testid="planning-tab-material">Material plan</TabsTrigger>
        </TabsList>
        {crewAllowed && <TabsContent value="crew"><PlanTab kind="crew" /></TabsContent>}
        <TabsContent value="material"><PlanTab kind="material" /></TabsContent>
      </Tabs>
    </div>
  );
}
