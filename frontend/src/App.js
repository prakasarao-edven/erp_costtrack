import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Show, SignIn, SignUp } from "@clerk/react";
import { Toaster } from "@/components/ui/sonner";
import ClerkAuthProvider from "@/components/auth/ClerkAuthProvider";
import { AppProvider, useApp } from "@/context/AppContext";
import Layout from "@/components/Layout";
import { Loading } from "@/components/common";
import Dashboard from "@/pages/Dashboard";
import Planning from "@/pages/Planning";
import UsageEntry from "@/pages/UsageEntry";
import MaterialEntry from "@/pages/MaterialEntry";
import Approvals from "@/pages/Approvals";
import RateCards from "@/pages/RateCards";
import Setup from "@/pages/Setup";
import Reports from "@/pages/Reports";
import ErpSync from "@/pages/ErpSync";
import Users from "@/pages/Users";
import Pending from "@/pages/Pending";
import MasterData from "@/pages/MasterData";
import MasterList from "@/pages/MasterList";

const AuthShell = ({ children }) => (
  <div className="cb-grid-bg flex min-h-screen">
    <div className="relative hidden w-1/2 overflow-hidden lg:flex">
      <img src="https://images.unsplash.com/photo-1575281923032-f40d94ef6160?crop=entropy&cs=srgb&fm=jpg&q=80&w=1400" alt="Construction site"
        className="absolute inset-0 h-full w-full object-cover opacity-50" />
      <div className="absolute inset-0 bg-gradient-to-t from-[#0B0F17] via-[#0B0F17]/60 to-transparent" />
      <div className="relative mt-auto p-12">
        <div className="cb-eyebrow mb-3">Edvenswa Technologies</div>
        <h1 className="text-5xl font-extrabold tracking-tight">CostBridge</h1>
        <p className="mt-3 max-w-md text-muted-foreground">Capture labor, equipment and material actuals at the site, validate against plan and budget, and post costed transactions to your ERP.</p>
      </div>
    </div>
    <div className="flex flex-1 items-center justify-center p-6">{children}</div>
  </div>
);

const Gate = ({ k, children }) => {
  const { can } = useApp();
  return can(k) ? children : <Navigate to="/" replace />;
};

const Protected = () => {
  const { me, master, error } = useApp();
  if (error) return <div className="p-8 text-rose-400" data-testid="app-error">Could not load your account. Refresh to try again.</div>;
  if (!me) return <Loading />;
  if (me.role === "pending") return <Pending />;
  if (!master) return <Loading />;
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/planning" element={<Gate k="planning"><Planning /></Gate>} />
        <Route path="/labor" element={<Gate k="labor"><UsageEntry key="labor" type="labor" /></Gate>} />
        <Route path="/equipment" element={<Gate k="equipment"><UsageEntry key="equipment" type="equipment" /></Gate>} />
        <Route path="/material" element={<Gate k="material"><MaterialEntry /></Gate>} />
        <Route path="/approvals" element={<Gate k="approvals"><Approvals /></Gate>} />
        <Route path="/rate-cards" element={<Gate k="rates"><RateCards /></Gate>} />
        <Route path="/setup" element={<Gate k="setup"><Setup /></Gate>} />
        <Route path="/reports" element={<Gate k="reports"><Reports /></Gate>} />
        <Route path="/erp" element={<Gate k="erp"><ErpSync /></Gate>} />
        <Route path="/users" element={<Gate k="users"><Users /></Gate>} />
        <Route path="/master" element={<Gate k="master"><MasterData /></Gate>} />
        <Route path="/master/:entity" element={<Gate k="master"><MasterList /></Gate>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
};

function App() {
  return (
    <BrowserRouter>
      <ClerkAuthProvider>
        <Routes>
          <Route path="/sign-in/*" element={<AuthShell><SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" withSignUp /></AuthShell>} />
          <Route path="/sign-up/*" element={<AuthShell><SignUp routing="path" path="/sign-up" signInUrl="/sign-in" /></AuthShell>} />
          <Route path="/*" element={
            <>
              <Show when="signed-in"><AppProvider><Protected /></AppProvider></Show>
              <Show when="signed-out"><Navigate to="/sign-in" replace /></Show>
            </>
          } />
        </Routes>
        <Toaster theme="dark" richColors position="top-right" />
      </ClerkAuthProvider>
    </BrowserRouter>
  );
}

export default App;
