import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiProvider, useApiState } from "./api";
import { ToastProvider } from "./components/ui";
import { Shell } from "./components/Shell";
import QueueView from "./views/Queue";
import LiveView from "./views/Live";
import CaseFileView from "./views/CaseFile";
import ApprovalsView from "./views/Approvals";
import InsightsView from "./views/Insights";
import { LensMark } from "./components/LensMark";

function lastId(key: string) {
  try {
    return localStorage.getItem(key) || "HHG-014";
  } catch {
    return "HHG-014";
  }
}

function Gate() {
  const { api } = useApiState();
  if (!api) {
    return (
      <div className="flex h-full items-center justify-center bg-ink-900">
        <div className="flex items-center gap-3 text-sm text-ink-300">
          <LensMark size={28} spinning />
          Connecting to the investigation service
        </div>
      </div>
    );
  }
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<QueueView />} />
        <Route path="/live" element={<Navigate to={`/live/${lastId("fl.lastLive")}`} replace />} />
        <Route path="/live/:caseId" element={<LiveView />} />
        <Route path="/case" element={<Navigate to={`/case/${lastId("fl.lastCase")}`} replace />} />
        <Route path="/case/:caseId" element={<CaseFileView />} />
        <Route path="/approvals" element={<ApprovalsView />} />
        <Route path="/insights" element={<InsightsView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

export default function App() {
  return (
    <ApiProvider>
      <ToastProvider>
        <HashRouter>
          <Gate />
        </HashRouter>
      </ToastProvider>
    </ApiProvider>
  );
}
