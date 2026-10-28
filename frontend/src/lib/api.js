import axios from "axios";
import { useMemo } from "react";
import { useAuth } from "@clerk/react";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export function useApi() {
  const { getToken } = useAuth();
  return useMemo(() => {
    const inst = axios.create({ baseURL: API });
    inst.interceptors.request.use(async (c) => {
      const t = await getToken();
      if (t) c.headers.Authorization = `Bearer ${t}`;
      return c;
    });
    return inst;
  }, [getToken]);
}

export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => `${x.loc?.slice(-1)[0] || ""} ${x.msg}`).join("; ");
  return d || e?.message || "Something went wrong";
};

export const usd = (n) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(Number(n || 0));
export const num = (n, d = 1) => (n === null || n === undefined || n === "" ? "-" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d }));
export const today = () => new Date().toISOString().slice(0, 10);

export const ROLE_LABEL = {
  admin: "Admin", cost_controller: "Cost Controller", project_manager: "Project Manager",
  store_manager: "Store Manager", foreman: "Foreman", pending: "Awaiting access",
};
