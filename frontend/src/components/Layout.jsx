import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { UserButton } from "@clerk/react";
import {
  LayoutDashboard, CalendarDays, UserCheck, Truck, Boxes, CheckSquare, CreditCard, SlidersHorizontal,
  FileSpreadsheet, Database, ShieldCheck, Menu, X, Layers,
} from "lucide-react";
import { useApp } from "@/context/AppContext";
import { ROLE_LABEL, useApi } from "@/lib/api";

const NAV = [
  ["dashboard", "/", "Dashboard", LayoutDashboard],
  ["master", "/master", "Master Data", Layers],
  ["planning", "/planning", "Planning", CalendarDays],
  ["labor", "/labor", "Labor Entry", UserCheck],
  ["equipment", "/equipment", "Equipment Entry", Truck],
  ["material", "/material", "Material Entry", Boxes],
  ["approvals", "/approvals", "Approvals", CheckSquare],
  ["rates", "/rate-cards", "Rate Cards", CreditCard],
  ["setup", "/setup", "Setup", SlidersHorizontal],
  ["reports", "/reports", "Reports", FileSpreadsheet],
  ["erp", "/erp", "ERP Integration", Database],
  ["users", "/users", "Users & Roles", ShieldCheck],
];

const Sidebar = ({ onNav }) => {
  const { can } = useApp();
  return (
    <nav className="flex flex-col gap-0.5 p-3">
      {NAV.filter(([k]) => can(k)).map(([k, to, label, Icon]) => (
        <NavLink key={k} to={to} end={to === "/"} onClick={onNav} data-testid={`sidebar-nav-${k}`}
          className={({ isActive }) =>
            `group flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
              isActive ? "bg-amber-500/10 text-amber-400" : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground"}`}>
          <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
          {label}
        </NavLink>
      ))}
    </nav>
  );
};

const ErpPill = () => {
  const api = useApi();
  const [st, setSt] = useState(null);
  useEffect(() => {
    api.get("/erp/status").then((r) => setSt(r.data)).catch(() => {});
  }, [api]);
  if (!st) return null;
  return (
    <span data-testid="erp-status-pill" className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-1 text-xs text-muted-foreground md:inline-flex">
      <span className={`h-2 w-2 rounded-full ${st.connected ? "bg-emerald-500" : "bg-slate-500"}`} />
      {st.connected ? "Oracle Fusion PPM connected" : "Oracle not connected - sample data"}
    </span>
  );
};

export default function Layout({ children }) {
  const { me } = useApp();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => { setOpen(false); }, [loc.pathname]);
  return (
    <div className="min-h-screen bg-background">
      <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center justify-between border-b border-white/[0.08] bg-[#0B0F17]/90 px-4 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <button className="rounded p-1.5 hover:bg-white/5 lg:hidden" onClick={() => setOpen(!open)} data-testid="mobile-menu-btn">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex items-center gap-2">
            <div className="grid h-7 w-7 place-items-center rounded bg-amber-500 font-display text-sm font-extrabold text-black">C</div>
            <span className="font-display text-lg font-bold tracking-tight">CostBridge</span>
            <span className="hidden text-xs text-muted-foreground sm:inline">by Edvenswa</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ErpPill />
          <div className="text-right leading-tight">
            <div data-testid="topbar-user-name" className="text-sm font-medium">{me?.name}</div>
            <div data-testid="topbar-user-role" className="text-[11px] uppercase tracking-wider text-amber-400/90">{ROLE_LABEL[me?.role]}</div>
          </div>
          <UserButton />
        </div>
      </header>
      <aside className={`fixed bottom-0 left-0 top-14 z-20 w-64 overflow-y-auto border-r border-white/[0.08] bg-[#0B0F17] transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <Sidebar onNav={() => setOpen(false)} />
      </aside>
      {open && <div className="fixed inset-0 z-10 bg-black/60 lg:hidden" onClick={() => setOpen(false)} />}
      <main className="cb-grid-bg min-h-screen pt-14 lg:pl-64">
        <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-10">{children}</div>
      </main>
    </div>
  );
}
