import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Field } from "@/components/common";
import { errMsg, useApi } from "@/lib/api";

export default function NewCrewDialog({ projectNumber, onCreated }) {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [foreman, setForeman] = useState("");
  const create = async () => {
    try {
      const { data } = await api.post("/crews", { name, foreman, project_number: projectNumber });
      toast.success(`Crew ${data.name} created`);
      setOpen(false); setName(""); setForeman("");
      onCreated(data);
    } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" size="icon" variant="secondary" disabled={!projectNumber} title="New crew" data-testid="new-crew-btn"><Plus className="h-4 w-4" /></Button>
      </DialogTrigger>
      <DialogContent className="border-white/10 bg-card">
        <DialogHeader><DialogTitle>New crew for {projectNumber}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <Field label="Crew name"><input className="cb-input" value={name} onChange={(e) => setName(e.target.value)} data-testid="new-crew-name-input" placeholder="Crew-C (Structural)" /></Field>
          <Field label="Foreman"><input className="cb-input" value={foreman} onChange={(e) => setForeman(e.target.value)} data-testid="new-crew-foreman-input" /></Field>
        </div>
        <DialogFooter><Button disabled={!name.trim()} onClick={create} data-testid="new-crew-save-btn">Create crew</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
