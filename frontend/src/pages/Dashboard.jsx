import { useEffect, useState } from "react";
import { Bar as RBar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApp } from "@/context/AppContext";
import { Bar, Field, Loading, PageHeader, Sel, StatusBadge } from "@/components/common";
import { num, usd, useApi } from "@/lib/api";

const Kpi = ({ label, value, sub, testid, tone = "" }) => (
  <div className="cb-card p-5 cb-rise">
    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
    <div className={`num mt-2 text-2xl font-semibold ${tone}`} data-testid={testid}>{value}</div>
    {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
  </div>
);

const TYPE_LABEL = { labor: "Labor (hrs)", equipment: "Equipment (hrs)", material: "Material" };
const COLORS = { labor: "#F59E0B", equipment: "#3B82F6", material: "#06B6D4" };

export default function Dashboard() {
  const api = useApi();
  const { master, taskName } = useApp();
  const [project, setProject] = useState("");
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get("/dashboard", { params: project ? { project_number: project } : {} }).then((r) => setD(r.data));
  }, [api, project]);

  return (
    <div>
      <PageHeader eyebrow="Reports / Budget vs Actual" title="Dashboard"
        desc="Task-level consumption against ERP budget across labor, equipment and material - same logic as the entry-time budget check."
        actions={
          <Field label="Project" className="min-w-[260px]">
            <Sel data-testid="dashboard-project-select" value={project} placeholder="All projects" onChange={(e) => setProject(e.target.value)}
              options={master.projects.map((p) => ({ value: p.number, label: `${p.number} - ${p.name}` }))} />
          </Field>
        } />
      {!d ? <Loading /> : (
        <>
          <div className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Kpi label="Actual cost to date" value={usd(d.kpis.actual_cost)} sub="Submitted + approved" testid="kpi-actual-cost" />
            <Kpi label="Approved cost" value={usd(d.kpis.approved_cost)} sub="Ready for / posted to ERP" testid="kpi-approved-cost" />
            <Kpi label="Pending approval" value={usd(d.kpis.pending_cost)} sub={`${d.kpis.pending_count} entries · ${d.kpis.flagged_count} flagged`} testid="kpi-pending-cost" tone="text-amber-400" />
            <Kpi label="Over budget lines" value={d.kpis.over_budget} sub={`${d.kpis.erp_queue} cost lines in ERP queue`} testid="kpi-over-budget" tone={d.kpis.over_budget ? "text-rose-400" : ""} />
          </div>
          <div className="grid gap-6 xl:grid-cols-3">
            <div className="cb-card overflow-x-auto xl:col-span-2">
              <table className="w-full" data-testid="budget-vs-actual-table">
                <thead><tr><th className="cb-th">Task</th><th className="cb-th">Resource type</th><th className="cb-th text-right">Budgeted</th>
                  <th className="cb-th text-right">Actual</th><th className="cb-th w-40">% consumed</th><th className="cb-th">Status</th></tr></thead>
                <tbody>
                  {d.rows.map((r) => (
                    <tr key={r.id} className="cb-row">
                      <td className="cb-td"><div>{r.task_number}</div><div className="text-xs text-muted-foreground">{r.project_number} · {taskName(r.project_number, r.task_number)}</div></td>
                      <td className="cb-td">{r.resource_type === "material" ? `Material (${r.item_number}, ${r.uom})` : TYPE_LABEL[r.resource_type]}</td>
                      <td className="cb-td num text-right">{num(r.qty)}</td>
                      <td className="cb-td num text-right">{num(r.actual)}<div className="text-xs text-muted-foreground">{usd(r.actual_cost)}</div></td>
                      <td className="cb-td"><div className="num mb-1 text-xs">{r.pct}%</div><Bar pct={r.pct} /></td>
                      <td className="cb-td"><StatusBadge status={r.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="cb-card p-5">
              <div className="cb-eyebrow mb-4">Actual cost by resource type</div>
              <div className="h-64" data-testid="cost-by-type-chart">
                <ResponsiveContainer>
                  <BarChart data={Object.entries(d.cost_by_type).map(([k, v]) => ({ k, v }))}>
                    <XAxis dataKey="k" stroke="#6B7280" fontSize={12} tickFormatter={(k) => k[0].toUpperCase() + k.slice(1)} />
                    <YAxis stroke="#6B7280" fontSize={11} tickFormatter={(v) => `$${Math.round(v / 1000)}k`} />
                    <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} contentStyle={{ background: "#111827", border: "1px solid #374151" }} formatter={(v) => usd(v)} />
                    <RBar dataKey="v" radius={[4, 4, 0, 0]}>
                      {Object.keys(d.cost_by_type).map((k) => <Cell key={k} fill={COLORS[k]} />)}
                    </RBar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {Object.entries(d.cost_by_type).map(([k, v]) => (
                <div key={k} className="flex justify-between border-t border-white/5 py-2 text-sm">
                  <span className="capitalize text-muted-foreground">{k}</span><span className="num">{usd(v)}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
