import { useEffect, useMemo, useState } from "react";
import { Copy, Plus, Trash2, Wand2, Wand } from "lucide-react";
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
    desc: "One row per person, every hour type in its own column. Load the crew plan, apply default hours to everyone, or copy your previous entry - then fix only the exceptions. Bonuses go in the last columns." },
  equipment: { title: "Equipment Usage", eyebrow: "Capture / Equipment", res: "Equipment",
    desc: "One row per asset with Active, Idle, Maintenance and Downtime hours side by side, each costed at its own rate type. Maintenance / Downtime need a reason code and route to special approval." },
};
const WORST = ["matches", "within", "unplanned", "absent", "breach"];

const toRows = (lines, bonuses = []) => {
  const m = new Map();
  lines.forEach((l) => {
    const r = m.get(l.resource_number) || { resource_number: l.resource_number, present: l.present !== false, hours: {}, planned: {}, plan_line: false, reason_code: l.reason_code || "" };
    r.hours[l.hour_type] = l.present === false ? null : l.hours;
    if (l.plan_line || l.planned_hours != null) { r.planned[l.hour_type] = l.planned_hours; r.plan_line = true; }
    if (l.reason_code) r.reason_code = l.reason_code;
    m.set(l.resource_number, r);
  });
  bonuses.forEach((b) => { const r = m.get(b.resource_number); if (r) Object.assign(r, { bonus_type: b.bonus_type, bonus_amount: b.amount }); });
  return [...m.values()];
};

const toLines = (rows, codes, reasonCodes) => rows.flatMap((r) => codes.filter((c) => (r.hours[c] ?? 0) > 0 || r.planned[c] != null).map((c) => ({
  resource_number: r.resource_number, hour_type: c, hours: r.present ? Number(r.hours[c] || 0) : 0, present: r.present,
  plan_line: r.planned[c] != null, planned_hours: r.planned[c] ?? undefined, reason_code: reasonCodes.includes(c) && r.reason_code ? r.reason_code : undefined,
})));

export default function UsageEntry({ type }) {
  const { master, me } = useApp();
  const e = useEntry(type);
  const tx = TEXT[type];
  const showRates = me.role !== "foreman";
  const hourTypes = master.hour_types.filter((h) => h.resource_type === type);
  const codes = hourTypes.map((h) => h.code);
  const reasonCodes = hourTypes.filter((h) => h.requires_reason).map((h) => h.code);
  const resources = type === "labor" ? master.employees : master.equipment;
  const resOptions = useMemo(() => resources.map((r) => ({ value: r.number, label: `${r.number} - ${r.name}` })), [resources]);
  const reasons = master.reason_codes.filter((r) => r.resource_type === "equipment");
  const bonusTypes = master.lookups.filter((l) => l.type === "BONUS_TYPE" && l.status !== "Inactive").map((l) => l.meaning);
  const crews = master.crews.filter((c) => !e.header.project_number || c.project_number === e.header.project_number);
  const [rows, setRows] = useState([]);
  const [defaults, setDefaults] = useState({ REG: type === "labor" ? 8 : 6 });
  const locked = !!e.editing && !["draft", "rejected"].includes(e.editing.status);

  useEffect(() => {
    e.setLines(toLines(rows, codes, reasonCodes));
    e.setBonuses(rows.filter((r) => r.bonus_type && Number(r.bonus_amount) > 0).map((r) => ({ resource_number: r.resource_number, bonus_type: r.bonus_type, amount: Number(r.bonus_amount) })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);
  useEffect(() => {
    if (e.editing) setRows(toRows(e.editing.lines, e.editing.bonuses));
    else if (!e.lines.length) setRows([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [e.editing]);

  const setRow = (i, patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const bonusDefault = (r, bt) => {
    const br = master.bonus_rates.find((b) => b.bonus_type === bt);
    if (!br || br.amount == null) return "";
    const hrs = Object.values(r.hours).reduce((s, v) => s + Number(v || 0), 0);
    return Math.round((br.basis === "per_hour" ? br.amount * hrs : br.amount) * 100) / 100;
  };
  const applyDefaults = () => setRows((rs) => rs.map((r) => (r.present ? { ...r, hours: { ...r.hours, ...Object.fromEntries(Object.entries(defaults).filter(([, v]) => v !== "" && v != null)) } } : r)));
  const loadPlan = async () => {
    const h = e.header;
    if (!h.project_number || !h.task_number || !h.crew_id || !h.date) return toast.error("Select project, task, crew and date first");
    try {
      const { data } = await e.api.get("/plans/autofill", { params: { type, ...h } });
      if (!data.plan || !data.lines.length) { e.setMode("manual"); e.setPlanId(null); return toast.info("No published plan for this crew/date - use defaults or manual rows"); }
      e.setMode("plan"); e.setPlanId(data.plan.id); setRows(toRows(data.lines));
      toast.success(`Loaded ${toRows(data.lines).length} ${type === "labor" ? "people" : "assets"} from plan`);
    } catch (err) { toast.error(errMsg(err)); }
  };
  const copyPrev = () => {
    const prev = e.recent.find((t) => t.project_number === e.header.project_number && t.task_number === e.header.task_number) || e.recent[0];
    if (!prev) return toast.info("No previous entry to copy");
    e.setMode("manual"); e.setPlanId(null);
    setRows(toRows(prev.lines.map((l) => ({ ...l, plan_line: false, planned_hours: null, present: true })), prev.bonuses).map((r) => ({ ...r, planned: {}, plan_line: false })));
    toast.success(`Copied rows from ${prev.ref}`);
  };
  const pv = (r) => {
    const ls = (e.preview?.lines || []).filter((l) => l.resource_number === r.resource_number);
    if (!ls.length) return null;
    return { cost: ls.reduce((s, l) => s + l.cost, 0), missing: ls.some((l) => l.rate_missing), status: ls.map((l) => l.tolerance_status).sort((a, b) => WORST.indexOf(b) - WORST.indexOf(a))[0] };
  };

  return (
    <div>
      <PageHeader eyebrow={tx.eyebrow} title={tx.title} desc={tx.desc} actions={e.editing && <Button variant="outline" onClick={() => { e.reset(); setRows([]); }} data-testid="entry-new-btn">New entry</Button>} />
      {e.editing && <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm" data-testid="editing-banner">Editing <span className="num">{e.editing.ref}</span>
        {e.editing.status === "rejected" && <> - rejected: <span className="text-rose-300">{e.editing.rejection_reason}</span>. Resubmitting restarts the approval chain.</>}</div>}
      <div className="cb-card mb-4 grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-5 cb-rise">
        <ProjectTaskFields testid={`${type}-entry`} value={e.header} onChange={(p) => e.setHeader((h) => ({ ...h, ...p, ...(p.project_number !== undefined ? { crew_id: "" } : {}) }))} />
        <Field label="Crew / Team"><Sel data-testid={`${type}-entry-crew-select`} value={e.header.crew_id} placeholder="(none)" onChange={(ev) => e.setHeader((h) => ({ ...h, crew_id: ev.target.value }))} options={crews.map((c) => ({ value: c.id, label: c.name }))} /></Field>
        <Field label="Date"><input type="date" className="cb-input" data-testid={`${type}-entry-date-input`} value={e.header.date} onChange={(ev) => e.setHeader((h) => ({ ...h, date: ev.target.value }))} /></Field>
        <div className="flex items-end"><Button onClick={loadPlan} variant="secondary" className="w-full" data-testid={`${type}-load-plan-btn`}><Wand2 className="mr-1.5 h-4 w-4" />Load from plan</Button></div>
      </div>
      <div className="cb-card mb-4 flex flex-wrap items-end gap-3 p-3" data-testid={`${type}-defaults-bar`}>
        <span className="cb-eyebrow mr-2 self-center">Default hours</span>
        {hourTypes.map((h) => (
          <Field key={h.code} label={h.name}><input type="number" min="0" max="24" step="0.5" className="cb-input num w-20 text-right" data-testid={`${type}-default-${h.code}`}
            value={defaults[h.code] ?? ""} onChange={(ev) => setDefaults({ ...defaults, [h.code]: ev.target.value === "" ? undefined : Number(ev.target.value) })} /></Field>
        ))}
        <Button size="sm" variant="secondary" onClick={applyDefaults} disabled={!rows.length} data-testid={`${type}-apply-defaults-btn`}><Wand className="mr-1 h-4 w-4" />Apply to all rows</Button>
        <Button size="sm" variant="ghost" onClick={copyPrev} data-testid={`${type}-copy-prev-btn`}><Copy className="mr-1 h-4 w-4" />Copy previous entry</Button>
        <Button size="sm" variant="ghost" className="ml-auto" data-testid={`${type}-add-line-btn`}
          onClick={() => setRows((rs) => [...rs, { resource_number: "", present: true, hours: { ...defaults }, planned: {}, plan_line: false, reason_code: "" }])}><Plus className="mr-1 h-4 w-4" />Add row</Button>
      </div>
      <div className="mb-2 text-xs text-muted-foreground" data-testid="entry-mode-label">Mode: <span className="text-amber-400">{e.mode === "plan" ? "Auto-filled from published plan (planned hours shown under each cell)" : "Manual bulk entry"}</span></div>
      <div className="cb-card mb-6 overflow-x-auto">
        <table className="w-full" data-testid={`${type}-lines-table`}>
          <thead><tr>
            <th className="cb-th">Present</th><th className="cb-th">{tx.res}</th>
            {hourTypes.map((h) => <th key={h.code} className="cb-th text-right">{h.name}</th>)}
            {type === "equipment" && <th className="cb-th">Reason code</th>}
            {type === "labor" && <><th className="cb-th">Bonus type</th><th className="cb-th text-right">Bonus $</th></>}
            <th className="cb-th text-right">Total hrs</th><th className="cb-th">vs Plan</th>{showRates && <th className="cb-th text-right">Est. cost</th>}<th className="cb-th" />
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={20} className="p-8 text-center text-sm text-muted-foreground">Load from plan, copy your previous entry, or add rows.</td></tr>}
            {rows.map((r, i) => {
              const t = `${type}-row-${i}`;
              const p = pv(r);
              const total = Object.values(r.hours).reduce((s, v) => s + Number(v || 0), 0);
              return (
                <tr key={i} className={`cb-row ${!r.present ? "opacity-50" : ""}`}>
                  <td className="cb-td"><input type="checkbox" className="h-4 w-4 accent-amber-500" checked={r.present} data-testid={`${t}-present-checkbox`} onChange={(ev) => setRow(i, { present: ev.target.checked })} /></td>
                  <td className="cb-td min-w-[220px]">
                    {r.plan_line ? <span>{resources.find((x) => x.number === r.resource_number)?.name || r.resource_number} <span className="num text-xs text-muted-foreground">{r.resource_number}</span></span>
                      : <Pick listId={`${type}-res-list`} testid={`${t}-resource-select`} value={r.resource_number} options={resOptions} onChange={(v) => setRow(i, { resource_number: v })} />}
                  </td>
                  {codes.map((c) => (
                    <td key={c} className="cb-td w-20">
                      <input type="number" min="0" max="24" step="0.5" className="cb-input num text-right" disabled={!r.present} data-testid={`${t}-hours-${c}`}
                        value={r.present ? r.hours[c] ?? "" : ""} onChange={(ev) => setRow(i, { hours: { ...r.hours, [c]: ev.target.value === "" ? null : Number(ev.target.value) } })} />
                      {r.planned[c] != null && <div className="num mt-0.5 text-right text-[10px] text-muted-foreground">plan {r.planned[c]}</div>}
                    </td>
                  ))}
                  {type === "equipment" && <td className="cb-td min-w-[160px]"><Sel data-testid={`${t}-reason-select`} value={r.reason_code || ""} placeholder="-" onChange={(ev) => setRow(i, { reason_code: ev.target.value })}
                    options={reasons.map((x) => ({ value: x.code, label: `${x.code} - ${x.name}` }))} /></td>}
                  {type === "labor" && <>
                    <td className="cb-td min-w-[130px]"><Sel data-testid={`${t}-bonus-type`} value={r.bonus_type || ""} placeholder="-" options={bonusTypes.map((b) => ({ value: b, label: b }))}
                      onChange={(ev) => setRow(i, { bonus_type: ev.target.value, bonus_amount: ev.target.value ? bonusDefault(r, ev.target.value) : "" })} /></td>
                    <td className="cb-td w-24"><input type="number" min="0" step="0.01" className="cb-input num text-right" data-testid={`${t}-bonus-amount`} value={r.bonus_amount ?? ""}
                      disabled={!r.bonus_type} onChange={(ev) => setRow(i, { bonus_amount: ev.target.value })} /></td>
                  </>}
                  <td className="cb-td num text-right">{num(total)}</td>
                  <td className="cb-td">{p?.status && <StatusBadge status={p.status} testid={`${t}-tolerance-badge`} />}</td>
                  {showRates && <td className="cb-td num text-right">{p ? (p.missing ? <span className="text-rose-400">no rate</span> : usd(p.cost + (Number(r.bonus_amount) || 0))) : "-"}</td>}
                  <td className="cb-td"><button onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-rose-400" data-testid={`${t}-remove-btn`}><Trash2 className="h-4 w-4" /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <DataList id={`${type}-res-list`} options={resOptions} />
      <ValidationPanel tx={e.preview} />
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button variant="outline" disabled={e.busy || locked || !e.lines.length} onClick={() => e.save("draft")} data-testid={`${type}-save-draft-btn`}>Save draft</Button>
        <Button disabled={e.busy || locked || !e.lines.length || e.preview?.validation?.blocked} onClick={async () => { if (await e.save("submit")) setRows([]); }} data-testid={`${type}-submit-btn`}>Submit for approval</Button>
        {e.preview?.validation?.blocked && <span className="text-xs text-rose-400">Resolve the issues above before submitting.</span>}
        {e.preview && <span className="num ml-auto text-sm text-muted-foreground">{num(e.preview.totals.qty, 2)} hrs{showRates && ` · ${usd(e.preview.totals.cost)}`}{e.preview.totals.bonus ? ` (incl. bonus ${usd(e.preview.totals.bonus)})` : ""}</span>}
      </div>
      <RecentEntries items={e.recent} onEdit={e.edit} />
    </div>
  );
}
