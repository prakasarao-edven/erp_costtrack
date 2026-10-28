import { useCallback, useEffect, useState } from "react";
import { DownloadCloud, PlugZap, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { Empty, Loading, PageHeader, Sel, StatusBadge } from "@/components/common";
import { errMsg, usd, useApi } from "@/lib/api";

const ENTITIES = [["projects", "Projects"], ["tasks", "Tasks / WBS"], ["employees", "Workers (HCM)"], ["items", "Item costs"], ["budgets", "Budget versions"]];

export default function ErpSync() {
  const api = useApi();
  const { me, reloadMaster } = useApp();
  const admin = me.role === "admin";
  const [st, setSt] = useState(null);
  const [costs, setCosts] = useState([]);
  const [batches, setBatches] = useState([]);
  const [filter, setFilter] = useState("queued");
  const [busy, setBusy] = useState(false);
  const [payload, setPayload] = useState(null);

  const load = useCallback(async () => {
    const [a, b, c] = await Promise.all([api.get("/erp/status"), api.get("/erp/batches"), api.get("/erp/cost-transactions", { params: filter ? { status: filter } : {} })]);
    setSt(a.data); setBatches(b.data); setCosts(c.data);
  }, [api, filter]);
  useEffect(() => { load(); }, [load]);

  const run = async (fn, okMsg) => {
    setBusy(true);
    try { const r = await fn(); toast.success(okMsg(r.data)); await load(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const test = () => run(() => api.post("/erp/test"), (d) => (d.ok ? "Connection OK" : `Connection failed (${d.status}) ${d.message}`));
  const sync = (entities) => run(async () => { const r = await api.post("/erp/sync", { entities }); await reloadMaster(); return r; },
    (d) => d.map((b) => `${b.entity}: ${b.status} (${b.count})`).join(" · "));
  const push = () => run(() => api.post("/erp/push"), (d) => `Pushed ${d.ok}/${d.count} cost lines${d.failed ? `, ${d.failed} failed` : ""}`);

  if (!st) return <Loading />;
  return (
    <div>
      <PageHeader eyebrow="Integration" title="Oracle Fusion PPM" desc="Batch, bi-directional: pull master data and budgets, push approved costed transactions to Unprocessed Project Costs. Adapter-based so SAP can be added later." />
      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <div className="cb-card p-5" data-testid="erp-connection-card">
          <div className="cb-eyebrow mb-3">Connection</div>
          <div className="flex items-center gap-2 text-lg font-semibold">
            <span className={`h-2.5 w-2.5 rounded-full ${st.connected ? "bg-emerald-500" : "bg-slate-500"}`} />
            {st.connected ? "Configured" : "Not configured"}
          </div>
          <p className="mt-2 break-all text-xs text-muted-foreground" data-testid="erp-base-url">{st.connected ? st.base_url : "Add the Oracle Fusion URL and integration user to connect. Until then, CostBridge runs on sample master data and approved costs wait in the queue."}</p>
          <Button className="mt-4" size="sm" variant="secondary" disabled={!st.connected || busy} onClick={test} data-testid="erp-test-connection-btn"><PlugZap className="mr-1.5 h-4 w-4" />Test connection</Button>
        </div>
        <div className="cb-card p-5">
          <div className="cb-eyebrow mb-3">Pull master data</div>
          <div className="flex flex-wrap gap-2">
            {ENTITIES.map(([k, l]) => <Button key={k} size="sm" variant="outline" disabled={!st.connected || !admin || busy} onClick={() => sync([k])} data-testid={`erp-sync-${k}-btn`}>{l}</Button>)}
          </div>
          <Button className="mt-3" size="sm" disabled={!st.connected || !admin || busy} onClick={() => sync(ENTITIES.map(([k]) => k))} data-testid="erp-sync-master-data-btn">
            <DownloadCloud className="mr-1.5 h-4 w-4" />Sync all
          </Button>
        </div>
        <div className="cb-card p-5">
          <div className="cb-eyebrow mb-3">Push costs</div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["queued", "Queued"], ["sent", "Sent"], ["error", "Errors"]].map(([k, l]) => (
              <div key={k}><div className="num text-2xl font-semibold" data-testid={`erp-count-${k}`}>{st.counts[k]}</div><div className="text-xs text-muted-foreground">{l}</div></div>
            ))}
          </div>
          <Button className="mt-4 w-full" disabled={!st.connected || busy || !(st.counts.queued + st.counts.error)} onClick={push} data-testid="erp-push-batches-btn">
            <UploadCloud className="mr-1.5 h-4 w-4" />Push queued to Oracle
          </Button>
        </div>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold md:text-lg">Cost transactions</h3>
        <Sel className="w-48" data-testid="erp-cost-filter" value={filter} placeholder="All" onChange={(e) => setFilter(e.target.value)}
          options={["queued", "sent", "error", "recorded", "sample"].map((s) => ({ value: s, label: s }))} />
      </div>
      {costs.length === 0 ? <Empty>No cost lines in this state.</Empty> : (
        <div className="cb-card mb-8 overflow-x-auto">
          <table className="w-full" data-testid="erp-cost-table">
            <thead><tr><th className="cb-th">Reference</th><th className="cb-th">Kind</th><th className="cb-th">Project / Task</th><th className="cb-th text-right">Amount</th>
              <th className="cb-th">Status</th><th className="cb-th">Oracle response</th><th className="cb-th" /></tr></thead>
            <tbody>{costs.map((c) => (
              <tr key={c.id} className="cb-row">
                <td className="cb-td num text-xs">{c.ref}</td><td className="cb-td text-xs">{c.kind.replace(/_/g, " ")}</td>
                <td className="cb-td text-sm">{c.payload.ProjectNumber} / {c.payload.TaskNumber}</td>
                <td className="cb-td num text-right">{usd(c.amount)}</td><td className="cb-td"><StatusBadge status={c.status} /></td>
                <td className="cb-td num text-xs text-muted-foreground">{c.response ? `HTTP ${c.response.status}` : c.kind === "return_to_store" ? "Inventory return - logged" : "-"}</td>
                <td className="cb-td"><button className="text-xs text-amber-400 hover:underline" onClick={() => setPayload(c)} data-testid={`erp-payload-btn-${c.ref}`}>Payload</button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      <h3 className="mb-3 text-base font-semibold md:text-lg">Batch log</h3>
      {batches.length === 0 ? <Empty>No batches run yet.</Empty> : (
        <div className="cb-card overflow-x-auto">
          <table className="w-full" data-testid="erp-batch-table">
            <thead><tr><th className="cb-th">Started</th><th className="cb-th">Direction</th><th className="cb-th">Entity</th><th className="cb-th text-right">Records</th><th className="cb-th">Status</th><th className="cb-th">By</th><th className="cb-th">Error</th></tr></thead>
            <tbody>{batches.map((b) => (
              <tr key={b.id} className="cb-row"><td className="cb-td num text-xs">{new Date(b.started_at).toLocaleString()}</td><td className="cb-td">{b.direction}</td>
                <td className="cb-td">{b.entity}</td><td className="cb-td num text-right">{b.count}</td><td className="cb-td"><StatusBadge status={b.status} /></td>
                <td className="cb-td">{b.by}</td><td className="cb-td max-w-xs truncate text-xs text-rose-300">{b.error}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <Dialog open={!!payload} onOpenChange={(o) => !o && setPayload(null)}>
        <DialogContent className="max-w-2xl border-white/10 bg-card">
          <DialogHeader><DialogTitle>{payload?.ref}</DialogTitle></DialogHeader>
          <pre className="num max-h-[60vh] overflow-auto rounded bg-black/40 p-3 text-xs" data-testid="erp-payload-json">{JSON.stringify(payload?.payload, null, 2)}</pre>
          {payload?.response && <pre className="num max-h-40 overflow-auto rounded bg-black/40 p-3 text-xs text-muted-foreground">{JSON.stringify(payload.response, null, 2)}</pre>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
