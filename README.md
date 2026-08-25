# AutoPick

本地运行的工厂审核报告选图工具。Vue3 负责图片审核和文字搜图，Python/FastAPI 负责项目隔离、千问向量、图片质量分析和 Word 报告生成。

## 一键启动

- **桌面客户端启动**：双击根目录下的 `AutoPick快捷启动.lnk` 或 `启动AutoPick.bat` 即可一键启动本地服务与 Windows 桌面窗口。
- **开发热重载模式**：双击 `启动开发模式(Dev).bat` 同时启动后端 API 与前端 Vite 实时开发服务。

## 开发与构建步骤

1. 设置 `DASHSCOPE_API_KEY`（在 `.env` 中已配置）。
2. 安装 Python 依赖：`python -m pip install -r requirements.txt`。
3. 安装前端依赖：在 `frontend` 中执行 `npm install`。
4. 后端：`python -m backend.run`。
5. 前端：在 `frontend` 中执行 `npm run dev`。
6. 构建前端静态资源：在 `frontend` 中执行 `npm run build`。

后端默认只监听 `127.0.0.1:8787`。生产模式由 Python 提供已构建的 Vue 静态文件，并可通过 `python -m backend.desktop` 启动 Windows 桌面壳。

## 桌面打包

运行 `scripts/build_desktop.ps1` 会先构建Vue静态资源，再生成 `dist/AutoPick/AutoPick.exe`。使用 Inno Setup 打开 `installer/AutoPick.iss` 即可制作安装包。安装后的项目数据默认存放在 `%LOCALAPPDATA%/AutoPickData`，不会写入安装目录。

## 数据隔离

每个项目拥有自己的 `project.sqlite`、原图快照、派生图、向量、OCR 和报告清单。全局数据库只保存清单、模板映射和不带图片引用的偏好统计。图片搜索接口始终要求项目 ID，并且在读取文件、检索向量和导出报告时重复验证项目归属。
