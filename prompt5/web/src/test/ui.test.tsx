import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppProvider } from "../components/AppContext";
import { demoIR } from "../demo-data/demo";
import { api } from "../lib/api";
import { BenchmarkPage } from "../pages/BenchmarkPage";
import { EvaluationPage } from "../pages/EvaluationPage";
import { IrEditorPage } from "../pages/IrEditorPage";
import { SettingsPage } from "../pages/SettingsPage";
import { WorkbenchPage } from "../pages/WorkbenchPage";

function renderWithApp(ui: React.ReactElement, route = "/") {
  return render(<MemoryRouter initialEntries={[route]}><AppProvider>{ui}</AppProvider></MemoryRouter>);
}

describe("Prompt5 UI acceptance", () => {
  it("requires a human rubric confirmation before generation", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(api, "confirmRubric");
    renderWithApp(<WorkbenchPage />);

    await user.click(screen.getByRole("button", { name: "创建任务" }));
    expect(await screen.findByText("等待人工确认")).toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();

    const checkbox = screen.getByRole("checkbox", { name: /我已阅读并确认/ });
    await waitFor(() => expect(checkbox).toBeEnabled());
    await user.click(checkbox);
    const confirmButton = screen.getByRole("button", { name: "确认并生成" });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    await user.click(confirmButton);
    expect(await screen.findByText("生成与 L1 检查已完成")).toBeInTheDocument();
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Mock 生成 · 不代表目标模型真实输出/)).toBeInTheDocument();
  }, 12000);

  it("shows scripted and B1-OSS declarations in evaluation", async () => {
    renderWithApp(<EvaluationPage />, "/evaluation");
    expect((await screen.findAllByText("模拟执行器·不构成效果证据")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/开源专家模板基线，非人工盲写基线/).length).toBeGreaterThan(0);
    expect(screen.getByText("McNemar p")).toBeInTheDocument();
    expect(screen.getByText("20", { selector: ".tab-count" })).toBeInTheDocument();
  });

  it("blocks saving invalid config with a concrete error code", async () => {
    const user = userEvent.setup();
    renderWithApp(<SettingsPage />, "/settings");
    const endpoint = await screen.findByLabelText("OpenAI 兼容服务端点");
    await user.clear(endpoint);
    await user.click(screen.getByRole("button", { name: "保存配置" }));
    expect(await screen.findByText(/个错误阻止保存/)).toBeInTheDocument();
    expect(screen.getByText("E_CONFIG_ENDPOINT_MISSING")).toBeInTheDocument();
  });

  it("stages IR edits as Patch and never applies them in demo mode", async () => {
    const user = userEvent.setup();
    renderWithApp(<IrEditorPage />, "/editor");
    const role = await screen.findByDisplayValue(demoIR.slots.role);
    await waitFor(() => expect(role).toBeEnabled());
    await user.clear(role);
    await user.type(role, "新的角色");
    await user.tab();
    expect(await screen.findByText("REWRITE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用 Patch" })).toBeDisabled();
  });

  it("keeps hidden benchmark tasks invisible", async () => {
    const user = userEvent.setup();
    renderWithApp(<BenchmarkPage />, "/benchmark");
    expect(await screen.findByText("基准任务")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /隐藏/ }));
    expect(screen.getByText("隐藏任务按设计不可见；这里显示 0 条是正确行为。")).toBeInTheDocument();
    expect(screen.getByText("frozen_at")).toBeInTheDocument();
  });
});
