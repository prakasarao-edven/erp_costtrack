import { useCallback, useEffect, useState } from "react";
import { Flag } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { Empty, Loading, PageHeader, StatusBadge } from "@/components/common";
import TxDetail from "@/components/TxDetail";
import { errMsg, num, usd, useApi } from "@/lib/api";

const TYPES = ["all", "labor", "equipment", "material"];

export default function Approvals() {
  const api = useApi();
  const [items, setItems] = useState(null);
  const [type, setType] = useState("all");
  const [flagged, setFlagged] = useState(false);
  const [sel, setSel] = useState(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get("/approvals");
    setItems(data);
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const shown = (items || []).filter((t) => (type === "all" || t.type === type) && (!flagged || t.validation.special.required));

  const act = async (kind) => {
    setBusy(true);
    try {
      const { data } = kind === "approve"
        ? await api.post(`/transactions/${sel.id}/approve`, { comment: "" })
        : await api.post(`/transactions/${sel.id}/reject`, { reason });
      toast.success(kind === "approve" ? `${data.ref} approved - now ${data.status.replace("_", " ")}` : `${data.ref} rejected`);
      setSel(null); setRejecting(false); setReason("");
      load();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader eyebrow="Workflow" title="Approvals" desc="One queue across labor, equipment and material for your approval step. Flagged entries (downtime, wastage) need special approval." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {TYPES.map((t) => (
          <button key={t} onClick={() => setType(t)} data-testid={`approvals-filter-${t}`}
            className={`rounded-md border px-3 py-1.5 text-sm capitalize transition-colors ${type === t ? "border-amber-500 bg-amber-500/10 text-amber-300" : "border-white/10 text-muted-foreground hover:text-foreground"}`}>
            {t === "all" ? "All types" : t}
          </button>
        ))}
        <button onClick={() => setFlagged(!flagged)} data-testid="approvals-filter-flagged"
          className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm ${flagged ? "border-rose-500 bg-rose-500/10 text-rose-300" : "border-white/10 text-muted-foreground"}`}>
          <Flag className="h-3.5 w-3.5" />Flagged only
        </button>
      </div>
      {!items ? <Loading /> : shown.length === 0 ? <Empty>Nothing waiting for your approval.</Empty> : (
        <div className="cb-card overflow-x-auto">
          <table className="w-full" data-testid="approvals-table">
            <thead><tr><th className="cb-th">Ref</th><th className="cb-th">Type</th><th className="cb-th">Project / Task</th><th className="cb-th">Submitted by</th>
              <th className="cb-th text-right">Qty</th><th className="cb-th text-right">Cost</th><th className="cb-th">Flag</th><th className="cb-th">Step</th><th className="cb-th" /></tr></thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.id} className="cb-row cursor-pointer" onClick={() => setSel(t)} data-testid={`approval-row-${t.ref}`}>
                  <td className="cb-td num text-xs">{t.ref}</td>
                  <td className="cb-td capitalize">{t.type}</td>
                  <td className="cb-td">{t.project_number} / {t.task_number}</td>
                  <td className="cb-td">{t.submitted_by}</td>
                  <td className="cb-td num text-right">{num(t.totals.qty, 2)} {t.totals.uom}</td>
                  <td className="cb-td num text-right">{usd(t.totals.cost)}</td>
                  <td className="cb-td">
                    {t.validation.special.required && <StatusBadge status="breach" label={t.type === "material" ? "Wastage" : "Downtime"} />}
                    {t.validation.tolerance.breach && <span className="ml-1"><StatusBadge status="warning" label="Tolerance" /></span>}
                    {t.validation.budget.status === "exceeded" && <span className="ml-1"><StatusBadge status="exceeded" label="Over budget" /></span>}
                  </td>
                  <td className="cb-td"><StatusBadge status={t.status} /></td>
                  <td className="cb-td text-right text-xs text-amber-400">Review</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto border-white/10 bg-[#0B0F17] sm:max-w-3xl">
          <SheetHeader><SheetTitle className="font-display">Review {sel?.type} entry</SheetTitle></SheetHeader>
          {sel && (
            <div className="mt-4">
              <TxDetail tx={sel} />
              <div className="mt-6 flex gap-3">
                <Button variant="outline" onClick={() => setRejecting(true)} disabled={busy} data-testid="approval-reject-btn">Reject</Button>
                <Button onClick={() => act("approve")} disabled={busy} data-testid="approval-approve-btn">
                  {sel.status === "pending_step2" ? "Approve & Post" : "Approve"}
                </Button>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent className="border-white/10 bg-card">
          <DialogHeader><DialogTitle>Reject {sel?.ref}</DialogTitle></DialogHeader>
          <Textarea placeholder="Reason (required) - returned to the submitter" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="reject-reason-input" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejecting(false)}>Cancel</Button>
            <Button variant="destructive" disabled={reason.trim().length < 3 || busy} onClick={() => act("reject")} data-testid="reject-confirm-btn">Reject entry</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
