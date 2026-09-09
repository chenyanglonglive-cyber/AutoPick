# AutoPick：AI Agent 配置与运行清单

本文件面向接手此仓库的 AI Agent。按以下约定配置、运行和修改项目，避免将客户业务数据写入代码仓库，或破坏固定 Excel 清单的版式。

## 1. 项目定位与当前主流程

- AutoPick 是本地运行的工厂审核清单选图工具。
- 当前正式清单类型为 `quality_v1`（Quality Checklist，199 个图片字段）和 `social_audit_v1`（Social Audit Checklist，36 个预留图片字段）。
- 同一项目的图库、图片向量和 OCR 由所有清单共享；字段、候选、确认、别名、反馈与训练准备度按清单类型隔离。
- 标准流程：导入图库 → 建立图片向量 → 本地 OCR（可选但推荐）→ 切换至所需清单重新匹配 → 人工复核 → 导出 `.xlsx`。
- Word 最终报告仅用于导入历史样本、学习字段别名和比对结果；不作为日常导出格式。
- 自动确认必须遵循“一图一字段”。同一张图只能自动填入一个字段；人工确认才允许显式复用。

## 2. 环境配置

在仓库根目录复制 `.env.example` 为 `.env`，不要提交 `.env`。

```ini
DASHSCOPE_API_KEY=你的 DashScope 密钥
AUTOPICK_DATA_ROOT=./AutoPickData
AUTOPICK_DEMO_EMBEDDINGS=0
AUTOPICK_QWEN_MAX_RETRIES=8
AUTOPICK_TRAINING_FEEDBACK_THRESHOLD=500
```

- 真实匹配需要 `DASHSCOPE_API_KEY`。
- 仅做 UI 演示时可将 `AUTOPICK_DEMO_EMBEDDINGS=1`；该模式不能用于真实审核结果。
- 建议把 `AUTOPICK_DATA_ROOT` 设为仓库外的绝对路径，确保业务数据与代码物理分离。
- Windows 打包版默认使用 `%LOCALAPPDATA%/AutoPickData/`。
- `AUTOPICK_TRAINING_FEEDBACK_THRESHOLD` 控制训练数据准备度提醒阈值；达到后只提醒接入训练模型，不会自动训练。

安装依赖：

```powershell
python -m pip install -r requirements.txt
Set-Location frontend
pnpm install
```

要求：Python 3.12+、Node.js 20+、pnpm、Windows（桌面端依赖 pywebview/WebView2）。

## 3. 正确运行方式

### 浏览器开发模式

在仓库根目录启动后端：

```powershell
python -m backend.run
```

在另一终端启动前端：

```powershell
Set-Location frontend
pnpm run dev
```

后端监听 `http://127.0.0.1:8787`。前端由 Vite 输出的本地地址访问。

### 桌面运行模式

```powershell
python -m backend.desktop
```

它会启动或复用本地 API，并打开 pywebview 窗口。

## 4. 数据与文件边界

```text
代码与内置资源：仓库根目录
业务运行数据：<AUTOPICK_DATA_ROOT>/
├─ global.sqlite                 # 本机共享别名/偏好
└─ projects/<project-uuid>/
   ├─ project.sqlite             # 单项目元数据、向量、候选、确认记录
   ├─ originals/                 # 项目原图副本
   ├─ derived/embedding/         # 向量化派生图
   ├─ derived/ocr/               # OCR 派生图
   ├─ templates/<checklist-type>.xlsx  # 项目模板副本
   ├─ outputs/                   # 导出结果
   └─ history/                   # 导入的最终 Word 历史报告
```

- `AutoPickData/` 已被 Git 忽略。不要提交项目数据库、客户照片、导出 Excel、历史报告或 `.env`。
- `resources/checklists/quality_v1/Quality list.xlsx` 和 `resources/checklists/social_audit_v1/Social Audit Checklist.xlsx` 是随代码发布的空白固定模板，可提交；不要用客户导出的 Excel 覆盖它。
- 清空项目图库只能影响当前项目副本，不能删除外部源图库。

## 5. 修改匹配或导出时的硬约束

1. 保持每种固定清单的工作表名、字段坐标、合并单元格、列宽、行高和样式。
2. 图片只能插入定义的 `image_cell`，不能把文字标签覆盖掉。
3. 自动选图不允许在同一清单内复用照片；不同清单之间与人工确认允许显式复用。
4. 历史 Word 学到的高置信度别名必须写入 `checklist_aliases`，因为重新匹配实际从该表读取别名。
5. 所有业务反馈仅写入 `AUTOPICK_DATA_ROOT` 的 SQLite，不进入 Git。
6. 修改 Excel 读写后，要验证输出仍能由 Excel/LibreOffice 打开，且图片锚点正确。

## 6. 验证命令

```powershell
python -m pytest tests/test_excel_checklist.py tests/test_feedback_import.py -q
Set-Location frontend
pnpm run build
```

测试说明：当前新增的 Excel 导出、反馈导入、历史别名和自动不复用覆盖均应通过。运行完整 `python -m pytest -q` 前，注意现有跨项目索引测试可能因索引任务完成状态而超时；先确认该问题是否已修复，再把完整套件作为交付门槛。

## 7. 提交前检查

```powershell
git status --short
git diff --check
python -m pytest tests/test_excel_checklist.py tests/test_feedback_import.py -q
```

只提交代码、测试、文档和内置空白模板。看到 `AutoPickData/`、客户文件或密钥出现在待提交列表时，应停止并移出暂存区。
