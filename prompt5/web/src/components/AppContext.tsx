import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { demoIR } from "../demo-data/demo";
import { API_MODE } from "../lib/api";
import type { PromptIR, TaskEnvelope } from "../types";

interface AppContextValue {
  currentIR: PromptIR | null;
  currentTask: TaskEnvelope | null;
  currentModel: string;
  setCurrentModel: (model: string) => void;
  setCurrentIR: (ir: PromptIR | null) => void;
  setCurrentTask: (task: TaskEnvelope | null) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [currentIR, setCurrentIR] = useState<PromptIR | null>(API_MODE === "demo" ? demoIR : null);
  const [currentTask, setCurrentTaskState] = useState<TaskEnvelope | null>(null);
  const [currentModel, setCurrentModel] = useState("deepseek");

  const value = useMemo<AppContextValue>(() => ({
    currentIR,
    currentTask,
    currentModel,
    setCurrentModel,
    setCurrentIR,
    setCurrentTask: (task) => {
      setCurrentTaskState(task);
      if (task?.ir) setCurrentIR(task.ir);
    },
  }), [currentIR, currentTask, currentModel]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used within AppProvider");
  return context;
}
