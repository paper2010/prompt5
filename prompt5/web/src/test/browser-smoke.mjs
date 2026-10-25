import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const baseURL = process.env.PROMPT5_UI_URL || "http://127.0.0.1:8765";
const executablePath = process.env.BROWSER_EXECUTABLE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const artifacts = new URL("../../test-results/", import.meta.url);
const artifactPath = (name) => fileURLToPath(new URL(name, artifacts));
await mkdir(artifacts, { recursive: true });

const browser = await chromium.launch({ executablePath, headless: true, args: ["--disable-gpu"] });
const errors = [];
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
const page = await context.newPage();
page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
page.on("response", (response) => {
  if (response.status() >= 500) errors.push(`HTTP ${response.status()}: ${response.url()}`);
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

try {
  for (const [route, heading] of [
    ["/", "把想法变成可用的提示词"],
    ["/editor", "看清每一次修改"],
    ["/evaluation", "用证据判断，而不是凭感觉"],
    ["/settings", "模型配置，集中一处完成"],
    ["/sessions", "每次反馈，都有迹可循"],
    ["/benchmark", "先冻结口径，再看结果"],
  ]) {
    await page.goto(`${baseURL}${route}`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: heading, exact: true }).waitFor();
  }
  console.log("PASS: six routes render without HTTP 5xx or page errors");

  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "创建任务" }).click();
  await page.getByText("等待人工确认").waitFor();
  assert(await page.getByText("生成与 L1 检查已完成").count() === 0, "generated before rubric confirmation");
  const checkbox = page.getByRole("checkbox", { name: /我已阅读并确认/ });
  await checkbox.waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector(".rubric-confirm-box input")?.disabled);
  await checkbox.check();
  await page.getByRole("button", { name: "确认并生成" }).click();
  await page.getByText("生成与 L1 检查已完成").waitFor();
  await page.getByText(/Mock 生成 · 不代表目标模型真实输出/).first().waitFor();
  await page.screenshot({ path: artifactPath("workbench-result.png"), fullPage: true });
  console.log("PASS: create -> human rubric confirmation -> IR/render/L1 result");

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "zh-CN" });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(baseURL, { waitUntil: "networkidle" });
  const metrics = await mobilePage.evaluate(() => {
    const viewport = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll("body *")].flatMap((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.right <= 0 || (rect.right <= viewport + 1 && rect.left >= -1)) return [];
      return [{ tag: element.tagName, class: element.className, left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) }];
    });
    return { viewport, scrollWidth: document.documentElement.scrollWidth, offenders: offenders.slice(0, 20) };
  });
  console.log("MOBILE_METRICS", JSON.stringify(metrics));
  assert(metrics.scrollWidth <= 391, `horizontal overflow: ${metrics.scrollWidth}px`);
  await mobilePage.getByRole("button", { name: "打开导航" }).click();
  await mobilePage.getByRole("navigation", { name: "主导航" }).waitFor({ state: "visible" });
  await mobilePage.getByRole("button", { name: "关闭导航" }).first().click();
  await mobilePage.screenshot({ path: artifactPath("home-mobile-verified.png"), fullPage: true });
  console.log("PASS: mobile has no horizontal overflow and navigation opens/closes");
  await mobile.close();

  assert(errors.length === 0, errors.join("\n"));
  console.log("PASS: browser smoke completed");
} finally {
  await browser.close();
}
