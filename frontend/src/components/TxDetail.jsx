import { StatusBadge } from "@/components/common";
import ValidationPanel from "@/components/ValidationPanel";
import { ROLE_LABEL, num, usd } from "@/lib/api";

const STEP = { submit: "Submitted", pending_step1: "Step 1 - Project Manager", pending_special: "Special approval", pending_step2: "Step 2 - Cost Controller", resubmit: "Resubmitted" };

const Lines = ({ tx }) => (
  <div className="cb-card overflow-x-auto">
    <table className="w-full">
      <thead><tr>
        {tx.type === "material" ? (
          <><th className="cb-th">Item</th><th className="cb-th text-right">Issued</th><th className="cb-th text-right">Wasted</th>
            <th className="cb-th text-right">Returned</th><th className="cb-th">Reason</th></>
        ) : (
          <><th className="cb-th">Resource</th><th className="cb-th">Hour type</th><th className="cb-th text-right">Planned</th>
            <th className="cb-th text-right">Actual</th><th className="cb-th">Reason / status</th></>
        )}
        <th className="cb-th text-right">Cost</th>
      </tr></thead>
      <tbody>
        {tx.lines.map((l, i) => (
          <tr key={i} className="cb-row">
            {tx.type === "material" ? (
              <><td className="cb-td">{l.item_name} <span className="num text-xs text-muted-foreground">{l.item_number}</span></td>
                <td className="cb-td num text-right">{num(l.qty_issued)} {l.uom}</td><td className="cb-td num text-right">{num(l.qty_wasted)}</td>
                <td className="cb-td num text-right">{num(l.qty_returned)}</td><td className="cb-td text-xs">{l.reason_code || "-"}</td></>
            ) : (
              <><td className="cb-td">{l.resource_name} <span className="num text-xs text-muted-foreground">{l.resource_number}</span></td>
                <td className="cb-td">{l.hour_type}</td><td className="cb-td num text-right">{l.planned_hours ?? "-"}</td>
                <td className="cb-td num text-right">{l.present === false ? "absent" : num(l.hours)}</td>
                <td className="cb-td text-xs">{l.reason_code || (l.tolerance_status && <StatusBadge status={l.tolerance_status} />)}</td></>
            )}
            <td className="cb-td num text-right">{usd(l.cost)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export default function TxDetail({ tx }) {
  return (
    <div className="space-y-5" data-testid="tx-detail">
      <div className="flex flex-wrap items-center gap-3">
        <span className="num text-sm">{tx.ref}</span><StatusBadge status={tx.status} />
        <span className="text-sm text-muted-foreground">{tx.project_number} / {tx.task_number} · {tx.date} · by {tx.submitted_by}</span>
        {tx.mode === "plan" && <span className="text-xs text-amber-400">From plan</span>}
      </div>
      <Lines tx={tx} />
      <ValidationPanel tx={tx} />
      <div>
        <div className="cb-eyebrow mb-2">Approval chain</div>
        <ol className="space-y-2 border-l border-white/10 pl-4">
          {(tx.approvals || []).map((a, i) => (
            <li key={i} className="text-sm">
              <span className={a.decision === "rejected" ? "text-rose-300" : a.decision === "approved" || a.decision === "auto-approved" ? "text-emerald-300" : ""}>
                {STEP[a.step] || a.step}: {a.decision}
              </span>
              <span className="text-muted-foreground"> - {a.by} ({ROLE_LABEL[a.role] || a.role}) · {new Date(a.at).toLocaleString()}</span>
              {a.comment && <div className="text-xs text-muted-foreground">{a.comment}</div>}
            </li>
          ))}
          {(!tx.approvals || tx.approvals.length === 0) && <li className="text-sm text-muted-foreground">No decisions yet.</li>}
        </ol>
      </div>
    </div>
  );
}
