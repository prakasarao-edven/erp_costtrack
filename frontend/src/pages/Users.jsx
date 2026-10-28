import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { Loading, PageHeader, Sel } from "@/components/common";
import { ROLE_LABEL, errMsg, useApi } from "@/lib/api";

const PERMS = [
  ["Planning", "PM, Foreman (crew); + Store Manager (material)"],
  ["Labor / Equipment entry", "Foreman, Project Manager"],
  ["Material entry", "Store Manager, Foreman"],
  ["Step 1 approval", "Project Manager"],
  ["Special + Step 2 approval", "Cost Controller (special approver configurable)"],
  ["Setup, users, master data sync", "Admin"],
];

export default function Users() {
  const api = useApi();
  const { me } = useApp();
  const [d, setD] = useState(null);
  const load = useCallback(async () => setD((await api.get("/users")).data), [api]);
  useEffect(() => { load(); }, [load]);
  const setRole = async (u, role) => {
    try { await api.patch(`/users/${u.user_id}/role`, { role }); toast.success(`${u.name} is now ${ROLE_LABEL[role]}`); load(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  if (!d) return <Loading />;
  return (
    <div>
      <PageHeader eyebrow="Security" title="Users & Roles" desc="People who sign up start as 'Awaiting access' with no data access until you assign them a role." />
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="cb-card overflow-x-auto xl:col-span-2">
          <table className="w-full" data-testid="users-table">
            <thead><tr><th className="cb-th">Name</th><th className="cb-th">Email</th><th className="cb-th">Role</th></tr></thead>
            <tbody>{d.users.map((u) => (
              <tr key={u.user_id} className="cb-row">
                <td className="cb-td">{u.name}{u.user_id === me.user_id && <span className="ml-2 text-xs text-amber-400">(you)</span>}</td>
                <td className="cb-td text-sm text-muted-foreground">{u.email}</td>
                <td className="cb-td w-56"><Sel data-testid={`user-role-select-${u.email}`} value={u.role} onChange={(e) => setRole(u, e.target.value)}
                  options={d.roles.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <div className="cb-card p-5">
          <div className="cb-eyebrow mb-3">Role permissions</div>
          {PERMS.map(([a, b]) => <div key={a} className="border-t border-white/5 py-2 text-sm"><div>{a}</div><div className="text-xs text-muted-foreground">{b}</div></div>)}
          <p className="mt-3 text-xs text-muted-foreground">Admin can perform every action. Approvers cannot approve their own entries.</p>
        </div>
      </div>
    </div>
  );
}
