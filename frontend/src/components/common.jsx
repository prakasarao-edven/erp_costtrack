import { useApp } from "@/context/AppContext";

const BADGE = {
  draft: ["Draft", "bg-slate-500/15 text-slate-300 border-slate-500/30"],
  pending_step1: ["Step 1 of 2", "bg-amber-500/15 text-amber-300 border-amber-500/30"],
  pending_special: ["Special approval", "bg-rose-500/15 text-rose-300 border-rose-500/30"],
  pending_step2: ["Step 2 of 2", "bg-blue-500/15 text-blue-300 border-blue-500/30"],
  approved: ["Approved - ERP queue", "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"],
  posted: ["Posted to ERP", "bg-cyan-500/15 text-cyan-300 border-cyan-500/30"],
  rejected: ["Rejected", "bg-rose-500/15 text-rose-300 border-rose-500/30"],
  published: ["Published", "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"],
  ok: ["OK", "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"],
  warning: ["Warning", "bg-amber-500/15 text-amber-300 border-amber-500/30"],
  exceeded: ["Exceeded", "bg-rose-500/15 text-rose-300 border-rose-500/30"],
  stopped: ["Stopped", "bg-rose-500/15 text-rose-300 border-rose-500/30"],
  no_budget: ["No budget", "bg-slate-500/15 text-slate-300 border-slate-500/30"],
  matches: ["Matches plan", "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"],
  within: ["Within tolerance", "bg-blue-500/15 text-blue-300 border-blue-500/30"],
  breach: ["Tolerance breach", "bg-rose-500/15 text-rose-300 border-rose-500/30"],
  absent: ["Absent / off", "bg-slate-500/15 text-slate-400 border-slate-500/30"],
  unplanned: ["Unplanned", "bg-slate-500/15 text-slate-300 border-slate-500/30"],
  queued: ["Queued", "bg-amber-500/15 text-amber-300 border-amber-500/30"],
  sent: ["Sent", "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"],
  error: ["Error", "bg-rose-500/15 text-rose-300 border-rose-500/30"],
  recorded: ["Recorded", "bg-slate-500/15 text-slate-300 border-slate-500/30"],
  sample: ["Sample - not sent", "bg-slate-500/15 text-slate-400 border-slate-500/30"],
  success: ["Success", "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"],
  partial: ["Partial", "bg-amber-500/15 text-amber-300 border-amber-500/30"],
};

export const StatusBadge = ({ status, label, testid }) => {
  const [l, cls] = BADGE[status] || [status, "bg-slate-500/15 text-slate-300 border-slate-500/30"];
  return (
    <span data-testid={testid} className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>
      {label || l}
    </span>
  );
};

export const PageHeader = ({ eyebrow, title, desc, actions }) => (
  <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between cb-rise">
    <div>
      <div className="cb-eyebrow mb-2">{eyebrow}</div>
      <h1 data-testid="page-title" className="text-3xl font-extrabold tracking-tight sm:text-4xl">{title}</h1>
      {desc && <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{desc}</p>}
    </div>
    {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
  </div>
);

export const Field = ({ label, children, className = "" }) => (
  <label className={`flex flex-col gap-1.5 ${className}`}>
    <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
    {children}
  </label>
);

export const Sel = ({ options, placeholder, className = "", ...p }) => (
  <select className={`cb-input ${className}`} {...p}>
    {placeholder !== undefined && <option value="">{placeholder}</option>}
    {options.map((o) => (
      <option key={o.value} value={o.value}>{o.label}</option>
    ))}
  </select>
);

export const ProjectTaskFields = ({ value, onChange, testid = "pt", disabled }) => {
  const { master } = useApp();
  const tasks = master.tasks.filter((t) => t.project_number === value.project_number);
  return (
    <>
      <Field label="Project #">
        <Sel data-testid={`${testid}-project-select`} disabled={disabled} value={value.project_number} placeholder="Select project"
          onChange={(e) => onChange({ project_number: e.target.value, task_number: "" })}
          options={master.projects.map((p) => ({ value: p.number, label: `${p.number} - ${p.name}` }))} />
      </Field>
      <Field label="Task #">
        <Sel data-testid={`${testid}-task-select`} disabled={disabled} value={value.task_number} placeholder="Select task"
          onChange={(e) => onChange({ task_number: e.target.value })}
          options={tasks.map((t) => ({ value: t.number, label: `${t.number} - ${t.name}` }))} />
      </Field>
    </>
  );
};

export const Bar = ({ pct }) => {
  const color = pct > 100 ? "bg-rose-500" : pct >= 90 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <div className={`h-full ${color} transition-[width] duration-700`} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  );
};

export const Empty = ({ children }) => (
  <div className="rounded-lg border border-dashed border-white/10 p-8 text-center text-sm text-muted-foreground">{children}</div>
);

export const Loading = () => (
  <div data-testid="loading" className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
    <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" /> Loading...
  </div>
);
