import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useApi } from "@/lib/api";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export const NAV_ROLES = {
  dashboard: ["admin", "cost_controller", "project_manager", "store_manager", "foreman"],
  planning: ["admin", "project_manager", "foreman", "store_manager"],
  labor: ["admin", "project_manager", "foreman"],
  equipment: ["admin", "project_manager", "foreman"],
  material: ["admin", "store_manager", "foreman"],
  approvals: ["admin", "project_manager", "cost_controller"],
  rates: ["admin", "cost_controller", "project_manager"],
  setup: ["admin"],
  reports: ["admin", "cost_controller", "project_manager", "store_manager", "foreman"],
  erp: ["admin", "cost_controller"],
  users: ["admin"],
};

export function AppProvider({ children }) {
  const api = useApi();
  const [me, setMe] = useState(null);
  const [master, setMaster] = useState(null);
  const [error, setError] = useState(null);

  const reloadMaster = useCallback(async () => {
    const { data } = await api.get("/master");
    setMaster(data);
  }, [api]);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/me");
        setMe(data);
        if (data.role !== "pending") await reloadMaster();
      } catch (e) {
        setError(e);
      }
    })();
  }, [api, reloadMaster]);

  const can = (key) => !!me && NAV_ROLES[key]?.includes(me.role);
  const taskName = (p, t) => master?.tasks.find((x) => x.project_number === p && x.number === t)?.name || t;

  return <Ctx.Provider value={{ me, master, reloadMaster, can, error, taskName }}>{children}</Ctx.Provider>;
}
