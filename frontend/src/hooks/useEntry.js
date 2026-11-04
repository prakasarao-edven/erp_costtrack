import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { errMsg, today, useApi } from "@/lib/api";

// Shared state for labor / equipment / material capture: header, lines, live preview, save/submit, recent list.
export function useEntry(type) {
  const api = useApi();
  const [header, setHeader] = useState({ project_number: "", task_number: "", crew_id: "", date: today(), notes: "" });
  const [mode, setMode] = useState("manual");
  const [planId, setPlanId] = useState(null);
  const [lines, setLines] = useState([]);
  const [bonuses, setBonuses] = useState([]);
  const [preview, setPreview] = useState(null);
  const [editing, setEditing] = useState(null);
  const [recent, setRecent] = useState([]);
  const [busy, setBusy] = useState(false);
  const timer = useRef();

  const body = useCallback((action) => ({
    type, ...header, crew_id: header.crew_id || null, plan_id: planId, mode, source: mode === "plan" ? "plan" : "manual", lines, bonuses, action,
  }), [type, header, planId, mode, lines, bonuses]);

  const loadRecent = useCallback(async () => {
    const { data } = await api.get("/transactions", { params: { type, mine: true } });
    setRecent(data.slice(0, 15));
  }, [api, type]);

  useEffect(() => { loadRecent(); }, [loadRecent]);

  const ready = header.project_number && header.task_number && header.date && lines.length > 0;
  useEffect(() => {
    clearTimeout(timer.current);
    if (!ready) { setPreview(null); return undefined; }
    timer.current = setTimeout(async () => {
      try {
        const { data } = await api.post("/transactions/preview", body("draft"));
        setPreview(data);
      } catch (e) {
        setPreview(null);
      }
    }, 350);
    return () => clearTimeout(timer.current);
  }, [api, body, ready]);

  const reset = () => {
    setLines([]); setBonuses([]); setPreview(null); setEditing(null); setMode("manual"); setPlanId(null);
  };

  const save = async (action) => {
    setBusy(true);
    try {
      const { data } = editing
        ? await api.put(`/transactions/${editing.id}`, body(action))
        : await api.post("/transactions", body(action));
      toast.success(action === "submit" ? `${data.ref} submitted - ${data.status.replace("_", " ")}` : `${data.ref} saved as draft`);
      if (action === "submit") reset(); else setEditing(data);
      loadRecent();
      return true;
    } catch (e) {
      toast.error(errMsg(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const edit = (tx) => {
    setEditing(tx);
    setHeader({ project_number: tx.project_number, task_number: tx.task_number, crew_id: tx.crew_id || "", date: tx.date, notes: tx.notes || "" });
    setMode(tx.mode); setPlanId(tx.plan_id || null);
    setLines(tx.lines.map((l) => ({ ...l })));
    setBonuses(tx.bonuses || []);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const setLine = (i, patch) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const removeLine = (i) => setLines((ls) => ls.filter((_, j) => j !== i));

  return { api, header, setHeader, mode, setMode, planId, setPlanId, lines, setLines, setLine, removeLine, bonuses, setBonuses, preview, editing, recent, busy, save, edit, reset };
}
