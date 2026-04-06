import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactElement } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import ApiKeys from "@/pages/ApiKeys";
import Approvals from "@/pages/Approvals";
import AuditLog from "@/pages/AuditLog";
import Connectors from "@/pages/Connectors";
import ConsoleSettings from "@/pages/ConsoleSettings";
import Dashboard from "@/pages/Dashboard";
import Login from "@/pages/Login";
import Memory from "@/pages/Memory";
import Policies from "@/pages/Policies";
import Providers from "@/pages/Providers";
import Workflows from "@/pages/Workflows";

const queryClient = new QueryClient();

function RequireAuth({ children }: { children: ReactElement }) {
  const apiKey = localStorage.getItem("sc_api_key");
  if (!apiKey) {
    return <Navigate to="/console/login" replace />;
  }
  return children;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/console/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/console" element={<Dashboard />} />
            <Route path="/console/approvals" element={<Approvals />} />
            <Route path="/console/connectors" element={<Connectors />} />
            <Route path="/console/workflows" element={<Workflows />} />
            <Route path="/console/providers" element={<Providers />} />
            <Route path="/console/policies" element={<Policies />} />
            <Route path="/console/memory" element={<Memory />} />
            <Route path="/console/audit" element={<AuditLog />} />
            <Route path="/console/api-keys" element={<ApiKeys />} />
            <Route path="/console/settings" element={<ConsoleSettings />} />
          </Route>
          <Route path="*" element={<Navigate to="/console" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
