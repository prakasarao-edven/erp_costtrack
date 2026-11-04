import { StatusBadge, Empty } from "@/components/common";
import { useApp } from "@/context/AppContext";
import { usd } from "@/lib/api";

export default function RecentEntries({ items, onEdit }) {
  const { me } = useApp();
  const showCost = me?.role !== "foreman";
  return (
    <div className="mt-10">
      <h3 className="mb-3 text-lg font-semibold">My recent entries</h3>
      {items.length === 0 ? <Empty>No entries yet.</Empty> : (
        <div className="cb-card overflow-x-auto">
          <table className="w-full" data-testid="recent-entries-table">
            <thead><tr><th className="cb-th">Ref</th><th className="cb-th">Project / Task</th><th className="cb-th">Date</th>
              {showCost && <th className="cb-th text-right">Cost</th>}<th className="cb-th">Status</th><th className="cb-th" /></tr></thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} className="cb-row">
                  <td className="cb-td num text-xs">{t.ref}</td>
                  <td className="cb-td">{t.project_number} / {t.task_number}</td>
                  <td className="cb-td num text-xs">{t.date}</td>
                  {showCost && <td className="cb-td num text-right">{usd(t.totals?.cost)}</td>}
                  <td className="cb-td">
                    <StatusBadge status={t.status} />
                    {t.status === "rejected" && <div className="mt-1 text-xs text-rose-300">Reason: {t.rejection_reason}</div>}
                  </td>
                  <td className="cb-td text-right">
                    {["draft", "rejected"].includes(t.status) && (
                      <button className="text-xs text-amber-400 hover:underline" onClick={() => onEdit(t)} data-testid={`recent-edit-btn-${t.ref}`}>
                        {t.status === "rejected" ? "Fix & resubmit" : "Edit"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
