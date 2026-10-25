# Prompt5 Desktop（Windows）

> **当前仅为内部测试版本，不能用于生产环境。** 安装包未签名，功能和数据兼容性均可能变化。

本目录提供 Windows 桌面客户端打包方案，基于：

- **Electron**：桌面窗口与安装器
- **PyInstaller**：把 FastAPI 后端打包成独立 `prompt5-backend.exe`
- **electron-builder**：生成 NSIS 安装包

## 一键构建

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-windows.ps1
```

脚本会依次完成：

1. 构建 `web/dist`
2. 安装 PyInstaller
3. 打包 FastAPI 后端为 `prompt5/dist/prompt5-backend.exe`
4. 生成 Windows 安装包到 `desktop/release/`

## 手动构建

```powershell
# 1. 构建前端
cd web
npm ci
npm run build
cd ..

# 2. 打包后端
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --name prompt5-backend `
  --add-data "web/dist;web/dist" `
  --add-data "config.example.yaml;." `
  --add-data "src/prompt5/store/schema.sql;prompt5/store" `
  --add-data "src/prompt5/store/schema_v2.sql;prompt5/store" `
  --collect-submodules prompt5 `
  --paths src `
  desktop/launcher.py

# 3. 打包桌面客户端
cd desktop
npm ci
npm run dist:win
```

## 产物

```text
desktop/release-windows/Prompt5-Setup-0.1.0.exe
```

## 本地调试

```powershell
cd desktop
npm start
```

会自动启动后端进程并打开窗口，无需手动配置端口。

## 说明

- 首次运行会自动使用内置默认配置和 SQLite 数据库。
- 演示模式完全离线可用。
- 如需真实模型评测，请在界面中的“模型与端点配置”填写 API Key。
- macOS 版本本次未实现。
