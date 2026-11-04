import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Download, Lock, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useApp } from "@/context/AppContext";
import { Field, Loading, PageHeader, Sel, StatusBadge } from "@/components/common";
import BulkUpload from "@/components/BulkUpload";
import { ENTITIES } from "@/lib/mdConfig";
import { errMsg, useApi } from "@/lib/api";

export const toCsv = (fields, rows) => [fields.map((f) => f[0]).join(","),
  ...rows.map((r) => fields.map((f) => `"${String(r[f[0]] ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");

const download = (name, text) => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" })); a.download = name; a.click();
};

const Input = ({ f, value, onChange, locked, lookups, master }) => {
  const [key, , type, , opt] = f;
  const p = { disabled: locked, "data-testid": `md-field-${key}`, value: value ?? (key === "status" ? "Active" : ""), onChange: (e) => onChange(e.target.value) };
  const withCur = (opts) => (value && !opts.some((o) => o.value === value) ? [{ value, label: value }, ...opts] : opts);
  if (type === "select") return <Sel {...p} placeholder="" options={withCur(opt.filter(Boolean).map((o) => ({ value: o, label: o })))} />;
  if (type === "lookup") return <Sel {...p} placeholder="" options={withCur(lookups.filter((l) => l.type === opt).map((l) => ({ value: l.meaning, label: l.meaning })))} />;
  if (type === "project") return <Sel {...p} placeholder="" options={master.projects.map((x) => ({ value: x.number, label: `${x.number} - ${x.name}` }))} />;
  if (type === "store") return <Sel {...p} placeholder="" options={master.stores.map((x) => ({ value: x.code, label: `${x.code} - ${x.name}` }))} />;
  if (type === "employee") return <input list="md-emp-list" className="cb-input" {...p} placeholder="Employee #" />;
  return <input className="cb-input" type={type === "date" ? "date" : type === "number" ? "number" : "text"} step="any" {...p} />;
};

export default function MasterList() {
  const { entity } = useParams();
  const cfg = ENTITIES[entity];
  const api = useApi();
  const { me, master, reloadMaster } = useApp();
  const editor = ["admin", "master_data_admin"].includes(me.role);
  const [f, setF] = useState({ q: "", status: "", source: "" });
  const [d, setD] = useState(null);
  const [rec, setRec] = useState(null);
  const [bulk, setBulk] = useState(false);
  const load = useCallback(async () => setD((await api.get(`/md/${entity}`, { params: f })).data), [api, entity, f]);
  useEffect(() => { load(); }, [load]);
  if (!cfg) return <div>Unknown entity</div>;
  const erp = rec?.source === "oracle";
  const lockedField = (k) => !editor || (erp && !d.lo.includes(k)) || (rec?.id && cfg.fields[0][0] === k && erp);

  const save = async (andNew) => {
    try {
      const { id, ...body } = rec;
      const { data } = id ? await api.put(`/md/${entity}/${id}`, body) : await api.post(`/md/${entity}`, body);
      toast.success("Saved"); setRec(andNew ? {} : data); load(); reloadMaster();
    } catch (e) { toast.error(errMsg(e)); }
  };
  const setStatus = async (status) => {
    try { await api.post(`/md/${entity}/${rec.id}/status`, { status }); toast.success(`Set ${status}`); setRec({ ...rec, status }); load(); reloadMaster(); }
    catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div>
      <PageHeader eyebrow={<Link to="/master" className="hover:underline">Master Data</Link>} title={cfg.label}
        desc={d ? `Source mode: ${d.mode.toUpperCase()} · ${d.total.toLocaleString()} records${d.total > 500 ? " (showing first 500 - search to narrow)" : ""}` : ""}
        actions={<>
          <Button variant="outline" onClick={() => download(`${entity}.csv`, toCsv(cfg.fields, d?.rows || []))} data-testid="md-export-btn"><Download className="mr-1.5 h-4 w-4" />Export</Button>
          {editor && <Button variant="outline" onClick={() => setBulk(true)} data-testid="md-bulk-btn"><Upload className="mr-1.5 h-4 w-4" />Bulk upload</Button>}
          {editor && d?.mode !== "erp" && <Button onClick={() => setRec({ status: "Active" })} data-testid="md-new-btn"><Plus className="mr-1.5 h-4 w-4" />New</Button>}
        </>} />
      <div className="cb-card mb-4 grid gap-3 p-4 sm:grid-cols-3">
        <input className="cb-input" placeholder={`Search ${cfg.keyLabel} or name`} value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} data-testid="md-search-input" />
        <Sel value={f.status} placeholder="All statuses" onChange={(e) => setF({ ...f, status: e.target.value })} options={["Active", "Inactive"].map((s) => ({ value: s, label: s }))} data-testid="md-status-filter" />
        <Sel value={f.source} placeholder="All sources" onChange={(e) => setF({ ...f, source: e.target.value })} options={[{ value: "erp", label: "ERP" }, { value: "local", label: "Local" }]} data-testid="md-source-filter" />
      </div>
      {!d ? <Loading /> : (
        <div className="cb-card overflow-x-auto">
          <table className="w-full" data-testid="md-table">
            <thead><tr>{cfg.cols.map((c) => <th key={c} className="cb-th">{cfg.fields.find((x) => x[0] === c)?.[1] || c}</th>)}<th className="cb-th">Source</th></tr></thead>
            <tbody>{d.rows.map((r) => (
              <tr key={r.id} className="cb-row cursor-pointer" onClick={() => setRec(r)} data-testid={`md-row-${cfg.fields[0][0] === "number" || cfg.fields[0][0] === "code" ? r[cfg.fields[0][0]] : `${r[cfg.fields[0][0]]}-${r[cfg.fields[1][0]]}`}`}>
                {cfg.cols.map((c) => <td key={c} className="cb-td text-sm">{c === "status" ? <StatusBadge status={r.status === "Inactive" ? "rejected" : "ok"} label={r.status || "Active"} /> : String(r[c] ?? "")}</td>)}
                <td className="cb-td text-xs">{r.source === "oracle" ? <span className="flex items-center gap-1 text-blue-300"><Lock className="h-3 w-3" />ERP</span> : "Local"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <datalist id="md-emp-list">{master.employees.slice(0, 3000).map((x) => <option key={x.number} value={x.number}>{x.name}</option>)}</datalist>
      <Sheet open={!!rec} onOpenChange={(o) => !o && setRec(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto border-white/10 bg-[#0B0F17] sm:max-w-xl">
          <SheetHeader><SheetTitle className="font-display">{rec?.id ? `Edit ${cfg.keyLabel} ${rec[cfg.fields[0][0]]}` : `New ${cfg.label}`}</SheetTitle></SheetHeader>
          {rec && (
            <div className="mt-4 space-y-4" data-testid="md-form">
              {erp && <div className="rounded-md border border-blue-500/30 bg-blue-500/5 px-3 py-2 text-xs text-blue-200" data-testid="md-erp-locked-note">
                ERP record (External ID {rec.external_id || rec.erp_id || "-"}, synced {rec.synced_at?.slice(0, 10) || "-"}). Only local-only (LO) fields can be edited.</div>}
              <div className="grid gap-4 sm:grid-cols-2">
                {cfg.fields.map((fl) => (
                  <Field key={fl[0]} label={`${fl[1]}${fl[3] ? " *" : ""}`}>
                    <Input f={fl} value={rec[fl[0]]} locked={lockedField(fl[0])} lookups={master.lookups} master={master} onChange={(v) => setRec({ ...rec, [fl[0]]: v })} />
                  </Field>
                ))}
              </div>
              {editor && (
                <div className="flex flex-wrap gap-2 pt-2">
                  <Button onClick={() => save(false)} data-testid="md-save-btn">Save</Button>
                  {!rec.id && <Button variant="outline" onClick={() => save(true)} data-testid="md-save-new-btn">Save & New</Button>}
                  {rec.id && !erp && <Button variant="ghost" onClick={() => setStatus(rec.status === "Inactive" ? "Active" : "Inactive")} data-testid="md-toggle-status-btn">
                    {rec.status === "Inactive" ? "Reactivate" : "Deactivate"}</Button>}
                </div>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
      <BulkUpload open={bulk} onOpenChange={setBulk} entity={entity} cfg={cfg} onDone={() => { load(); reloadMaster(); }} template={() => download(`${entity}-template.csv`, toCsv(cfg.fields, []))} />
    </div>
  );
}
