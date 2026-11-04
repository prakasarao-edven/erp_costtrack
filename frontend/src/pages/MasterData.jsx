import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Database, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { Loading, PageHeader, Sel } from "@/components/common";
import { ENTITIES } from "@/lib/mdConfig";
import { errMsg, useApi } from "@/lib/api";

const MODES = [{ value: "erp", label: "ERP-synced (read only)" }, { value: "local", label: "Local (maintained here)" }, { value: "hybrid", label: "Hybrid (both)" }];

export default function MasterData() {
  const api = useApi();
  const { me } = useApp();
  const [d, setD] = useState(null);
  const load = useCallback(async () => setD((await api.get("/md/summary")).data), [api]);
  useEffect(() => { load(); }, [load]);
  const setMode = async (entity, mode) => {
    try { await api.put("/md/source-modes", { modes: { [entity]: mode } }); toast.success(`${ENTITIES[entity].label}: ${mode}`); load(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  if (!d) return <Loading />;
  return (
    <div>
      <PageHeader eyebrow="Master Data" title="Master Data" desc="Run standalone or with an ERP. Each entity has its own source mode - ERP-synced records are read-only here except local-only (LO) fields; Local records are fully maintained in CostBridge." />
      {d.conflicts > 0 && (
        <div className="mb-6 flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm" data-testid="md-conflicts-banner">
          <AlertTriangle className="h-4 w-4 text-amber-400" />{d.conflicts} ERP records clash with local keys and were not overwritten (Sync Conflict queue).
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {d.entities.map((e) => (
          <div key={e.entity} className="cb-card flex flex-col p-5 cb-rise" data-testid={`md-tile-${e.entity}`}>
            <Link to={`/master/${e.entity}`} className="group flex items-start justify-between">
              <div>
                <div className="font-display text-lg font-semibold group-hover:text-amber-400">{ENTITIES[e.entity].label}</div>
                <div className="num mt-1 text-2xl">{e.total.toLocaleString()}</div>
                <div className="text-xs text-muted-foreground">{e.erp.toLocaleString()} from ERP · {(e.total - e.erp).toLocaleString()} local · {e.inactive} inactive</div>
              </div>
              <Database className="h-5 w-5 text-muted-foreground" />
            </Link>
            <div className="mt-4">
              <Sel data-testid={`md-mode-${e.entity}`} value={e.mode} disabled={me.role !== "admin"} onChange={(ev) => setMode(e.entity, ev.target.value)} options={MODES} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-6 text-xs text-muted-foreground">Hour types, approvals and tolerances live in Setup. Labor / equipment rates and bonuses live in Rate Cards.</p>
    </div>
  );
}
