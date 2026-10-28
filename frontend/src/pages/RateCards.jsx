import { useCallback, useEffect, useState } from "react";
import { Plus, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApp } from "@/context/AppContext";
import { Field, PageHeader, Sel } from "@/components/common";
import { errMsg, usd, useApi } from "@/lib/api";

const RateRow = ({ r, htName, admin, onSave }) => {
  const [v, setV] = useState(r);
  const dirty = v.base_rate !== r.base_rate || v.multiplier !== r.multiplier || v.premium !== r.premium;
  const eff = v.base_rate * v.multiplier + v.premium;
  const inp = (k) => (
    <input type="number" min="0" step="0.01" disabled={!admin} className="cb-input num w-24 text-right" data-testid={`rate-${r.resource_type}-${r.key}-${r.hour_type}-${k}`}
      value={v[k]} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} />
  );
  return (
    <tr className="cb-row">
      <td className="cb-td">{r.key}</td><td className="cb-td">{htName}</td>
      <td className="cb-td">{inp("base_rate")}</td><td className="cb-td">{inp("multiplier")}</td><td className="cb-td">{inp("premium")}</td>
      <td className="cb-td num text-right font-medium">{usd(eff)}/hr</td>
      <td className="cb-td num text-xs text-muted-foreground">{r.effective_from}</td>
      <td className="cb-td">{admin && dirty && <Button size="sm" onClick={() => onSave(v)} data-testid={`rate-save-${r.resource_type}-${r.key}-${r.hour_type}`}><Save className="h-3.5 w-3.5" /></Button>}</td>
    </tr>
  );
};

const AddRate = ({ type, hourTypes, onAdd }) => {
  const [v, setV] = useState({ key: "", hour_type: hourTypes[0]?.code || "", base_rate: 0, multiplier: 1, premium: 0 });
  return (
    <div className="mt-4 flex flex-wrap items-end gap-3">
      <Field label={type === "labor" ? "Grade" : "Equipment class"}><input className="cb-input w-44" data-testid={`add-rate-${type}-key`} value={v.key} onChange={(e) => setV({ ...v, key: e.target.value })} /></Field>
      <Field label="Hour type"><Sel className="w-40" value={v.hour_type} onChange={(e) => setV({ ...v, hour_type: e.target.value })} options={hourTypes.map((h) => ({ value: h.code, label: h.name }))} /></Field>
      <Field label="Base $/hr"><input type="number" className="cb-input w-28" data-testid={`add-rate-${type}-base`} value={v.base_rate} onChange={(e) => setV({ ...v, base_rate: Number(e.target.value) })} /></Field>
      <Field label="Multiplier"><input type="number" step="0.05" className="cb-input w-24" value={v.multiplier} onChange={(e) => setV({ ...v, multiplier: Number(e.target.value) })} /></Field>
      <Field label="Premium $/hr"><input type="number" className="cb-input w-24" value={v.premium} onChange={(e) => setV({ ...v, premium: Number(e.target.value) })} /></Field>
      <Button disabled={!v.key} onClick={() => onAdd({ ...v, resource_type: type })} data-testid={`add-rate-${type}-btn`}><Plus className="mr-1 h-4 w-4" />Add rate</Button>
    </div>
  );
};

const HourTypes = ({ admin }) => {
  const api = useApi();
  const { master, reloadMaster } = useApp();
  const save = async (h, patch) => {
    try { await api.put(`/hour-types/${h.id}`, { name: h.name, expenditure_type: h.expenditure_type, requires_reason: h.requires_reason, ...patch }); await reloadMaster(); toast.success("Hour type updated"); }
    catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="cb-card overflow-x-auto">
      <table className="w-full" data-testid="hour-types-table">
        <thead><tr><th className="cb-th">Resource</th><th className="cb-th">Code</th><th className="cb-th">Name</th><th className="cb-th">ERP expenditure type</th><th className="cb-th">Reason required</th></tr></thead>
        <tbody>
          {master.hour_types.map((h) => (
            <tr key={h.id} className="cb-row">
              <td className="cb-td capitalize">{h.resource_type}</td><td className="cb-td num text-xs">{h.code}</td><td className="cb-td">{h.name}</td>
              <td className="cb-td"><input className="cb-input" disabled={!admin} defaultValue={h.expenditure_type} data-testid={`hour-type-exp-${h.resource_type}-${h.code}`}
                onBlur={(e) => e.target.value !== h.expenditure_type && save(h, { expenditure_type: e.target.value })} /></td>
              <td className="cb-td"><input type="checkbox" className="h-4 w-4 accent-amber-500" disabled={!admin} checked={h.requires_reason}
                onChange={(e) => save(h, { requires_reason: e.target.checked })} data-testid={`hour-type-reason-${h.resource_type}-${h.code}`} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default function RateCards() {
  const api = useApi();
  const { me, master, reloadMaster } = useApp();
  const admin = me.role === "admin";
  const [rates, setRates] = useState([]);
  const load = useCallback(async () => setRates((await api.get("/rate-cards")).data), [api]);
  useEffect(() => { load(); }, [load]);
  const s = master.settings;

  const setSource = async (type, val) => {
    try { await api.put("/settings", { ...s, rate_source: { ...s.rate_source, [type]: val } }); await reloadMaster(); toast.success("Rate source updated"); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const saveRate = async (r) => { try { await api.put(`/rate-cards/${r.id}`, r); toast.success("Rate saved"); load(); } catch (e) { toast.error(errMsg(e)); } };
  const addRate = async (r) => { try { await api.post("/rate-cards", r); toast.success("Rate added"); load(); } catch (e) { toast.error(errMsg(e)); } };

  const table = (type) => {
    const hts = master.hour_types.filter((h) => h.resource_type === type);
    const rows = rates.filter((r) => r.resource_type === type).sort((a, b) => a.key.localeCompare(b.key) || hts.findIndex((h) => h.code === a.hour_type) - hts.findIndex((h) => h.code === b.hour_type));
    return (
      <>
        <div className="cb-card mb-4 flex flex-wrap items-center gap-4 p-4">
          <span className="text-sm">Rate source</span>
          {["app", "erp"].map((src) => (
            <button key={src} disabled={!admin} onClick={() => setSource(type, src)} data-testid={`rate-source-${type}-${src}`}
              className={`rounded-md border px-3 py-1.5 text-sm ${s.rate_source[type] === src ? "border-amber-500 bg-amber-500/10 text-amber-300" : "border-white/10 text-muted-foreground"}`}>
              {src === "app" ? "App-maintained" : "ERP-pulled"}
            </button>
          ))}
          <span className="text-xs text-muted-foreground">
            {s.rate_source[type] === "erp" ? "Oracle applies its own cost rates on import; rates below are used for in-app estimates only." : "Rates below cost every entry and are sent to Oracle as raw cost."}
          </span>
        </div>
        <div className="cb-card overflow-x-auto">
          <table className="w-full" data-testid={`rate-table-${type}`}>
            <thead><tr><th className="cb-th">{type === "labor" ? "Grade" : "Equipment class"}</th><th className="cb-th">Hour type</th><th className="cb-th">Base $/hr</th>
              <th className="cb-th">Multiplier</th><th className="cb-th">Premium $/hr</th><th className="cb-th text-right">Effective rate</th><th className="cb-th">From</th><th className="cb-th" /></tr></thead>
            <tbody>{rows.map((r) => <RateRow key={r.id} r={r} admin={admin} onSave={saveRate} htName={hts.find((h) => h.code === r.hour_type)?.name || r.hour_type} />)}</tbody>
          </table>
        </div>
        {admin && <AddRate type={type} hourTypes={hts} onAdd={addRate} />}
      </>
    );
  };

  return (
    <div>
      <PageHeader eyebrow="Setup / Master data" title="Rate Cards" desc="Rates per hour type / usage state with OT, bonus and premium multipliers. Effective rate = base x multiplier + premium." />
      <Tabs defaultValue="labor">
        <TabsList className="mb-6">
          <TabsTrigger value="labor" data-testid="rates-tab-labor">Labor</TabsTrigger>
          <TabsTrigger value="equipment" data-testid="rates-tab-equipment">Equipment</TabsTrigger>
          <TabsTrigger value="hours" data-testid="rates-tab-hours">Hour types</TabsTrigger>
          <TabsTrigger value="materials" data-testid="rates-tab-materials">Material cost (ERP)</TabsTrigger>
        </TabsList>
        <TabsContent value="labor">{table("labor")}</TabsContent>
        <TabsContent value="equipment">{table("equipment")}</TabsContent>
        <TabsContent value="hours"><HourTypes admin={admin} /></TabsContent>
        <TabsContent value="materials">
          <div className="cb-card overflow-x-auto">
            <table className="w-full" data-testid="item-cost-table">
              <thead><tr><th className="cb-th">Item</th><th className="cb-th">Description</th><th className="cb-th">UOM</th><th className="cb-th text-right">Unit cost</th><th className="cb-th">Source</th></tr></thead>
              <tbody>{master.items.map((i) => (
                <tr key={i.id} className="cb-row"><td className="cb-td num text-xs">{i.number}</td><td className="cb-td">{i.description}</td><td className="cb-td">{i.uom}</td>
                  <td className="cb-td num text-right">{usd(i.unit_cost)}</td><td className="cb-td text-xs capitalize text-muted-foreground">{i.source}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">Material cost is always pulled from the ERP item master - it is never maintained in CostBridge.</p>
        </TabsContent>
      </Tabs>
    </div>
  );
}
