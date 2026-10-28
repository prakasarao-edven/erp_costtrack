import { AlertTriangle, CheckCircle2, Flag, ShieldAlert } from "lucide-react";
import { Bar, StatusBadge } from "@/components/common";
import { num, usd } from "@/lib/api";

export default function ValidationPanel({ tx }) {
  if (!tx?.validation) return null;
  const v = tx.validation;
  return (
    <div className="grid gap-4 lg:grid-cols-3" data-testid="validation-panel">
      <div className="cb-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="cb-eyebrow">Budget check</span>
          <StatusBadge status={v.budget.status} testid="budget-status-badge" />
        </div>
        {v.budget.checks.length === 0 && <p className="text-sm text-muted-foreground">No ERP budget found for this task.</p>}
        {v.budget.checks.map((c) => (
          <div key={c.label} className="mb-3">
            <div className="mb-1 flex justify-between text-xs">
              <span>{c.label}</span>
              <span className="num">{num(c.after)} / {num(c.budget)} {c.uom} ({c.pct}%)</span>
            </div>
            <Bar pct={c.pct} />
          </div>
        ))}
        <p className="text-xs text-muted-foreground">Behavior: {v.budget.behavior === "stop" ? "Stopper (blocks submit)" : "Warning only"}</p>
      </div>
      <div className="cb-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="cb-eyebrow">Plan tolerance (±{v.tolerance.pct}%)</span>
          <StatusBadge status={!v.tolerance.has_plan ? "unplanned" : v.tolerance.breach ? "breach" : "within"} label={!v.tolerance.has_plan ? "No plan" : undefined} testid="tolerance-status-badge" />
        </div>
        <p className="text-sm text-muted-foreground">
          {!v.tolerance.has_plan ? "No published plan rows to compare against - manual entry." : v.tolerance.breach ? "One or more rows deviate from plan beyond tolerance - standard approval required." : "All planned rows are within tolerance."}
        </p>
        <p className="mt-2 text-xs text-muted-foreground">Behavior: {v.tolerance.behavior === "stop" ? "Stopper" : "Warning only"}</p>
        <div className="mt-3 flex items-center gap-2 text-sm" data-testid="auto-approval-eligibility">
          {v.unmodified_from_plan ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <AlertTriangle className="h-4 w-4 text-slate-400" />}
          {v.unmodified_from_plan ? "Unmodified from plan - eligible for auto-approval" : "Modified / manual - standard 2-step approval"}
        </div>
      </div>
      <div className="cb-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="cb-eyebrow">Totals & routing</span>
          {v.special.required && <span className="flex items-center gap-1 text-xs text-rose-300"><Flag className="h-3 w-3" />Special approval</span>}
        </div>
        <div className="num text-2xl font-semibold text-foreground" data-testid="entry-total-cost">{usd(tx.totals.cost)}</div>
        <div className="num text-xs text-muted-foreground">{num(tx.totals.qty, 2)} {tx.totals.uom}</div>
        {v.special.reasons.map((r) => <div key={r} className="mt-2 text-xs text-rose-300">{r}</div>)}
        {v.errors.map((e) => (
          <div key={e} className="mt-2 flex items-start gap-1.5 text-xs text-rose-400" data-testid="validation-error">
            <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />{e}
          </div>
        ))}
      </div>
    </div>
  );
}
