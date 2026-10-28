import { UserButton } from "@clerk/react";
import { ShieldAlert } from "lucide-react";
import { useApp } from "@/context/AppContext";

export default function Pending() {
  const { me } = useApp();
  return (
    <div className="cb-grid-bg flex min-h-screen items-center justify-center p-6">
      <div className="cb-card max-w-md p-8 text-center cb-rise" data-testid="pending-access">
        <ShieldAlert className="mx-auto mb-4 h-10 w-10 text-amber-500" />
        <h1 className="text-2xl font-bold">Awaiting access</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          You're signed in as <span className="text-foreground">{me?.email}</span>. An administrator needs to assign you a role
          (Foreman, Store Manager, Project Manager or Cost Controller) before you can use CostBridge.
        </p>
        <div className="mt-6 flex justify-center"><UserButton /></div>
      </div>
    </div>
  );
}
