import { useMemo } from "react";
import { Plus, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useEntry } from "@/hooks/useEntry";
import { errMsg, num, usd } from "@/lib/api";
import { DataList, Field, PageHeader, Pick, ProjectTaskFields, Sel, StatusBadge } from "@/components/common";
import ValidationPanel from "@/components/ValidationPanel";
import RecentEntries from "@/components/RecentEntries";

const TEXT = {
  labor: { title: "Labor Timesheet", eyebrow: "Capture / Labor", res: "Employee",
    desc: "Load the published crew plan and manage by exception - untick anyone absent and edit hours only where actuals differ. No plan? Enter the whole team manually." },
  equipment: { title: "Equipment Usage", eyebrow: "Capture / Equipment", res: "Equipment",
    desc: "Capture Active, Idle, Maintenance and Downtime hours, each on its own rate. Downtime and maintenance need a reason code and route to special approval." },
};

const LineRow = ({ i, ln, pv, type, e, resOptions, hourTypes, reasons }) => {
  const isPlan = ln.plan_line;
  const t = `${type}-line-${i}`;
  return (
    <tr className={`cb-row ${ln.present === false ? "opacity-50" : ""}`}>
      <td className="cb-td">
        {isPlan ? (
          <input type="checkbox" className="h-4 w-4 accent-amber-500" checked={ln.present !== false} data-testid={`${t}-present-checkbox`}
            onChange={(ev) => e.setLine(i, { present: ev.target.checked })} />
        ) : <span className="text-xs text-muted-foreground">-</span>}
      </td>
      <td className="cb-td min-w-[170px]">
        {isPlan ? <span>{pv?.resource_name || ln.resource_number} <span className="num text-xs text-muted-foreground">{ln.resource_number}</span></span> : (
          <Pick listId={`${type}-res-list`} testid={`${t}-resource-select`} value={ln.resource_number || ""} options={resOptions}
            onChange={(v) => e.setLine(i, { resource_number: v })} />
        )}
      </td>
      <td className="cb-td min-w-[140px]">
        {isPlan ? hourTypes.find((h) => h.code === ln.hour_type)?.name : (
          <Sel data-testid={`${t}-hourtype-select`} value={ln.hour_type || ""} placeholder="Select"
            onChange={(ev) => e.setLine(i, { hour_type: ev.target.value })} options={hourTypes.map((h) => ({ value: h.code, label: h.name }))} />
        )}
      </td>
      <td className="cb-td num text-right text-muted-foreground">{ln.planned_hours ?? "-"}</td>
      <td className="cb-td w-24">
        <input type="number" min="0" max="24" step="0.5" className="cb-input num text-right" disabled={ln.present === false}
          data-testid={`${t}-hours-input`} value={ln.present === false ? "" : ln.hours ?? ""}
          onChange={(ev) => e.setLine(i, { hours: ev.target.value === "" ? null : Number(ev.target.value) })} />
      </td>
      {type === "equipment" && (
        <td className="cb-td min-w-[170px]">
          <Sel data-testid={`${t}-reason-select`} value={ln.reason_code || ""} placeholder="-"
            onChange={(ev) => e.setLine(i, { reason_code: ev.target.value || null })}
            options={reasons.map((r) => ({ value: r.code, label: `${r.code} - ${r.name}` }))} />
        </td>
      )}
      <td className="cb-td num text-right text-xs">{pv?.vs_plan_pct === null || pv?.vs_plan_pct === undefined ? "-" : `${pv.vs_plan_pct > 0 ? "+" : ""}${pv.vs_plan_pct}%`}</td>
      <td className="cb-td">{pv?.tolerance_status && <StatusBadge status={pv.tolerance_status} testid={`${t}-tolerance-badge`} />}</td>
      <td className="cb-td num text-right text-xs">{pv ? (pv.rate_missing ? <span className="text-rose-400">no rate</span> : usd(pv.rate)) : "-"}</td>
      <td className="cb-td num text-right">{pv ? usd(pv.cost) : "-"}</td>
      <td className="cb-td">
        <button onClick={() => e.removeLine(i)} className="text-muted-foreground hover:text-rose-400" data-testid={`${t}-remove-btn`}><Trash2 className="h-4 w-4" /></button>
      </td>
    </tr>
  );
};

export default function UsageEntry({ type }) {
  const { master } = useApp();
  const e = useEntry(type);
  const tx = TEXT[type];
  const resources = type === "labor" ? master.employees : master.equipment;
  const resOptions = useMemo(() => resources.map((r) => ({ value: r.number, label: `${r.number} - ${r.name}` })), [resources]);
  const hourTypes = master.hour_types.filter((h) => h.resource_type === type);
  const reasons = master.reason_codes.filter((r) => r.resource_type === "equipment");
  const crews = master.crews.filter((c) => !e.header.project_number || c.project_number === e.header.project_number);
  const locked = !!e.editing && e.editing.status !== "draft" && e.editing.status !== "rejected";

  const loadPlan = async () => {
    const h = e.header;
    if (!h.project_number || !h.task_number || !h.crew_id || !h.date) return toast.error("Select project, task, crew and date first");
    try {
      const { data } = await e.api.get("/plans/autofill", { params: { type, ...h } });
      if (!data.plan || data.lines.length === 0) {
        e.setMode("manual"); e.setPlanId(null);
        return toast.info("No published plan for this crew/date - switch to manual entry");
      }
      e.setMode("plan"); e.setPlanId(data.plan.id); e.setLines(data.lines);
      toast.success(`Loaded ${data.lines.length} rows from plan`);
    } catch (err) { toast.error(errMsg(err)); }
  };

  return (
    <div>
      <PageHeader eyebrow={tx.eyebrow} title={tx.title} desc={tx.desc}
        actions={e.editing && <Button variant="outline" onClick={e.reset} data-testid="entry-new-btn">New entry</Button>} />
      {e.editing && (
        <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm" data-testid="editing-banner">
          Editing <span className="num">{e.editing.ref}</span>
          {e.editing.status === "rejected" && <> - rejected: <span className="text-rose-300">{e.editing.rejection_reason}</span>. Resubmitting restarts the approval chain.</>}
        </div>
      )}
      <div className="cb-card mb-6 grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-5 cb-rise">
        <ProjectTaskFields testid={`${type}-entry`} value={e.header} onChange={(p) => e.setHeader((h) => ({ ...h, ...p, ...(p.project_number !== undefined ? { crew_id: "" } : {}) }))} />
        <Field label="Crew / Team">
          <Sel data-testid={`${type}-entry-crew-select`} value={e.header.crew_id} placeholder="(none)" onChange={(ev) => e.setHeader((h) => ({ ...h, crew_id: ev.target.value }))}
            options={crews.map((c) => ({ value: c.id, label: c.name }))} />
        </Field>
        <Field label="Date">
          <input type="date" className="cb-input" data-testid={`${type}-entry-date-input`} value={e.header.date} onChange={(ev) => e.setHeader((h) => ({ ...h, date: ev.target.value }))} />
        </Field>
        <div className="flex items-end gap-2">
          <Button onClick={loadPlan} variant="secondary" className="w-full" data-testid={`${type}-load-plan-btn`}><Wand2 className="mr-1.5 h-4 w-4" />Load from plan</Button>
        </div>
      </div>

      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs text-muted-foreground" data-testid="entry-mode-label">
          Mode: <span className="text-amber-400">{e.mode === "plan" ? "Auto-filled from published plan" : "Manual bulk entry"}</span>
        </span>
        <Button size="sm" variant="ghost" data-testid={`${type}-add-line-btn`}
          onClick={() => e.setLines((ls) => [...ls, { resource_number: "", hour_type: hourTypes[0]?.code, hours: 8, present: true, plan_line: false }])}>
          <Plus className="mr-1 h-4 w-4" />Add row
        </Button>
      </div>
      <div className="cb-card mb-6 overflow-x-auto">
        <table className="w-full" data-testid={`${type}-lines-table`}>
          <thead><tr>
            <th className="cb-th">Present</th><th className="cb-th">{tx.res}</th><th className="cb-th">Hour type</th>
            <th className="cb-th text-right">Planned</th><th className="cb-th text-right">Actual hrs</th>
            {type === "equipment" && <th className="cb-th">Reason code</th>}
            <th className="cb-th text-right">vs Plan</th><th className="cb-th">Status</th><th className="cb-th text-right">Rate</th>
            <th className="cb-th text-right">Est. cost</th><th className="cb-th" />
          </tr></thead>
          <tbody>
            {e.lines.length === 0 && (
              <tr><td colSpan={11} className="p-8 text-center text-sm text-muted-foreground">Load from plan, or add rows for manual entry.</td></tr>
            )}
            {e.lines.map((ln, i) => (
              <LineRow key={i} i={i} ln={ln} pv={e.preview?.lines?.[i]} type={type} e={e} resOptions={resOptions} hourTypes={hourTypes} reasons={reasons} />
            ))}
          </tbody>
        </table>
      </div>

      <DataList id={`${type}-res-list`} options={resOptions} />
      <ValidationPanel tx={e.preview} />
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button variant="outline" disabled={e.busy || locked || !e.lines.length} onClick={() => e.save("draft")} data-testid={`${type}-save-draft-btn`}>Save draft</Button>
        <Button disabled={e.busy || locked || !e.lines.length || e.preview?.validation?.blocked} onClick={() => e.save("submit")} data-testid={`${type}-submit-btn`}>
          Submit for approval
        </Button>
        {e.preview?.validation?.blocked && <span className="text-xs text-rose-400">Resolve the issues above before submitting.</span>}
        {e.preview && <span className="num ml-auto text-sm text-muted-foreground">{num(e.preview.totals.qty, 2)} hrs · {usd(e.preview.totals.cost)}</span>}
      </div>
      <RecentEntries items={e.recent} onEdit={e.edit} />
    </div>
  );
}
