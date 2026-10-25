import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./components/AppContext";
import { AppShell } from "./components/AppShell";
import { WorkbenchPage } from "./pages/WorkbenchPage";
import { IrEditorPage } from "./pages/IrEditorPage";
import { EvaluationPage } from "./pages/EvaluationPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SessionsPage } from "./pages/SessionsPage";
import { BenchmarkPage } from "./pages/BenchmarkPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<WorkbenchPage />} />
            <Route path="editor" element={<IrEditorPage />} />
            <Route path="evaluation" element={<EvaluationPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="sessions" element={<SessionsPage />} />
            <Route path="benchmark" element={<BenchmarkPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
