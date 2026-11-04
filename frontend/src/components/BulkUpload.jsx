import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { errMsg, useApi } from "@/lib/api";

const parseCsv = (text) => {
  const rows = [];
  let row = [], cur = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cur); cur = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cur); rows.push(row); row = []; cur = ""; }
    else cur += c;
  }
  if (cur || row.length) { row.push(cur); rows.push(row); }
  const [head, ...body] = rows.filter((r) => r.some((x) => x.trim()));
  return (body || []).map((r) => Object.fromEntries(head.map((h, i) => [h.trim(), (r[i] || "").trim()])));
};

// Template -> validate -> review -> commit (BRD Addendum §6)
export default function BulkUpload({ open, onOpenChange, entity, cfg, onDone, template }) {
  const api = useApi();
  const [rows, setRows] = useState(null);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (commit) => {
    setBusy(true);
    try {
      const { data } = await api.post(`/md/${entity}/bulk`, { rows, commit, skip_errors: true });
      setRes(data);
      if (commit) { toast.success(`Committed ${data.committed} rows`); onDone(); }
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const pick = async (file) => { setRes(null); setRows(parseCsv(await file.text())); };
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) { setRows(null); setRes(null); } }}>
      <DialogContent className="max-w-3xl border-white/10 bg-card">
        <DialogHeader><DialogTitle>Bulk upload - {cfg.label}</DialogTitle></DialogHeader>
        <ol className="space-y-3 text-sm">
          <li>1. <button className="text-amber-400 underline" onClick={template} data-testid="bulk-template-btn">Download CSV template</button> (columns = field keys; existing key = update, new key = create)</li>
          <li>2. <input type="file" accept=".csv" onChange={(e) => e.target.files[0] && pick(e.target.files[0])} data-testid="bulk-file-input" className="text-xs" />
            {rows && <span className="ml-2 text-muted-foreground">{rows.length} rows read</span>}</li>
          <li>3. <Button size="sm" variant="secondary" disabled={!rows?.length || busy} onClick={() => run(false)} data-testid="bulk-validate-btn">Validate</Button></li>
        </ol>
        {res && (
          <div className="mt-2 space-y-3" data-testid="bulk-results">
            <div className="flex gap-4 text-sm"><span>New: <b className="num">{res.counts.new}</b></span><span>Update: <b className="num">{res.counts.update}</b></span>
              <span className="text-rose-300">Errors: <b className="num">{res.counts.error}</b></span>{res.committed > 0 && <span className="text-emerald-300">Committed: {res.committed}</span>}</div>
            <div className="max-h-60 overflow-y-auto rounded border border-white/10">
              {res.results.filter((r) => r.result === "error").slice(0, 200).map((r) => (
                <div key={r.row} className="border-b border-white/5 px-3 py-1.5 text-xs"><span className="num">Row {r.row}</span> {r.key} - <span className="text-rose-300">{r.error}</span></div>
              ))}
              {res.counts.error === 0 && <div className="p-3 text-xs text-emerald-300">All rows valid.</div>}
            </div>
            <Button disabled={busy || !(res.counts.new + res.counts.update) || res.committed > 0} onClick={() => run(true)} data-testid="bulk-commit-btn">
              Commit valid rows (skip errors)</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
