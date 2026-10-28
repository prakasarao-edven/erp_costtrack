import { useMemo } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useEntry } from "@/hooks/useEntry";
import { num, usd } from "@/lib/api";
import { DataList, Field, PageHeader, Pick, ProjectTaskFields, StatusBadge, Sel } from "@/components/common";
import ValidationPanel from "@/components/ValidationPanel";
import RecentEntries from "@/components/RecentEntries";

const QtyInput = ({ value, onChange, testid }) => (
  <input type="number" min="0" step="any" className="cb-input num w-24 text-right" data-testid={testid} value={value ?? ""}
    onChange={(ev) => onChange(ev.target.value === "" ? null : Number(ev.target.value))} />
);

export default function MaterialEntry() {
  const { master } = useApp();
  const e = useEntry("material");
  const reasons = master.reason_codes.filter((r) => r.resource_type === "material");
  const locked = !!e.editing && !["draft", "rejected"].includes(e.editing.status);
  const itemOptions = useMemo(() => master.items.map((x) => ({ value: x.number, label: `${x.number} - ${x.description}` })), [master.items]);

  return (
    <div>
      <PageHeader eyebrow="Capture / Material" title="Material Issue Entry"
        desc="Log material issued from the project store. Item and unit cost come from the ERP item master. Wasted or returned quantity creates a Return-to-Store record; wastage routes to special approval."
        actions={e.editing && <Button variant="outline" onClick={e.reset} data-testid="entry-new-btn">New entry</Button>} />
      {e.editing && (
        <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm" data-testid="editing-banner">
          Editing <span className="num">{e.editing.ref}</span>
          {e.editing.status === "rejected" && <> - rejected: <span className="text-rose-300">{e.editing.rejection_reason}</span></>}
        </div>
      )}
      <div className="cb-card mb-6 grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4 cb-rise">
        <ProjectTaskFields testid="material-entry" value={e.header} onChange={(p) => e.setHeader((h) => ({ ...h, ...p }))} />
        <Field label="Issue date">
          <input type="date" className="cb-input" data-testid="material-entry-date-input" value={e.header.date} onChange={(ev) => e.setHeader((h) => ({ ...h, date: ev.target.value }))} />
        </Field>
        <Field label="Notes">
          <input className="cb-input" data-testid="material-entry-notes-input" value={e.header.notes} placeholder="Store / issue slip ref"
            onChange={(ev) => e.setHeader((h) => ({ ...h, notes: ev.target.value }))} />
        </Field>
      </div>
      <div className="mb-2 flex justify-end">
        <Button size="sm" variant="ghost" data-testid="material-add-line-btn"
          onClick={() => e.setLines((ls) => [...ls, { item_number: "", qty_issued: null, qty_wasted: 0, qty_returned: 0 }])}>
          <Plus className="mr-1 h-4 w-4" />Add item
        </Button>
      </div>
      <div className="cb-card mb-6 overflow-x-auto">
        <table className="w-full" data-testid="material-lines-table">
          <thead><tr>
            <th className="cb-th">Item</th><th className="cb-th">UOM</th><th className="cb-th text-right">Unit cost (ERP)</th>
            <th className="cb-th text-right">Issued</th><th className="cb-th text-right">Wasted</th><th className="cb-th text-right">Returned</th>
            <th className="cb-th">Reason</th><th className="cb-th text-right">Consumed</th><th className="cb-th">vs Plan</th><th className="cb-th text-right">Cost</th><th className="cb-th" />
          </tr></thead>
          <tbody>
            {e.lines.length === 0 && <tr><td colSpan={11} className="p-8 text-center text-sm text-muted-foreground">Add the items issued.</td></tr>}
            {e.lines.map((ln, i) => {
              const pv = e.preview?.lines?.[i];
              const it = master.items.find((x) => x.number === ln.item_number);
              const t = `material-line-${i}`;
              return (
                <tr key={i} className="cb-row">
                  <td className="cb-td min-w-[220px]">
                    <Pick listId="material-item-list" testid={`${t}-item-select`} value={ln.item_number} options={itemOptions}
                      onChange={(v) => e.setLine(i, { item_number: v })} />
                  </td>
                  <td className="cb-td text-xs">{it?.uom || "-"}</td>
                  <td className="cb-td num text-right text-xs">{it ? usd(it.unit_cost) : "-"}</td>
                  <td className="cb-td"><QtyInput testid={`${t}-qty-issued-input`} value={ln.qty_issued} onChange={(v) => e.setLine(i, { qty_issued: v })} /></td>
                  <td className="cb-td"><QtyInput testid={`${t}-qty-wasted-input`} value={ln.qty_wasted} onChange={(v) => e.setLine(i, { qty_wasted: v })} /></td>
                  <td className="cb-td"><QtyInput testid={`${t}-qty-returned-input`} value={ln.qty_returned} onChange={(v) => e.setLine(i, { qty_returned: v })} /></td>
                  <td className="cb-td min-w-[170px]">
                    <Sel data-testid={`${t}-reason-select`} value={ln.reason_code || ""} placeholder="-" onChange={(ev) => e.setLine(i, { reason_code: ev.target.value || null })}
                      options={reasons.map((r) => ({ value: r.code, label: `${r.code} - ${r.name}` }))} />
                  </td>
                  <td className="cb-td num text-right">{pv ? num(pv.qty_consumed, 2) : "-"}</td>
                  <td className="cb-td">
                    {pv?.tolerance_status && <StatusBadge status={pv.tolerance_status} testid={`${t}-tolerance-badge`}
                      label={pv.planned_qty != null ? `${num(pv.period_used)} / ${num(pv.planned_qty)} (${pv.vs_plan_pct > 0 ? "+" : ""}${pv.vs_plan_pct}%)` : undefined} />}
                  </td>
                  <td className="cb-td num text-right">{pv ? usd(pv.cost) : "-"}</td>
                  <td className="cb-td"><button onClick={() => e.removeLine(i)} className="text-muted-foreground hover:text-rose-400" data-testid={`${t}-remove-btn`}><Trash2 className="h-4 w-4" /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <DataList id="material-item-list" options={itemOptions} />
      <ValidationPanel tx={e.preview} />
      <div className="mt-6 flex flex-wrap gap-3">
        <Button variant="outline" disabled={e.busy || locked || !e.lines.length} onClick={() => e.save("draft")} data-testid="material-save-draft-btn">Save draft</Button>
        <Button disabled={e.busy || locked || !e.lines.length || e.preview?.validation?.blocked} onClick={() => e.save("submit")} data-testid="material-submit-btn">Submit for approval</Button>
      </div>
      <RecentEntries items={e.recent} onEdit={e.edit} />
    </div>
  );
}
