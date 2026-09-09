# AutoPick

AutoPick 是本地运行的工厂审核清单选图工具。当前版本提供两份内置 Excel 清单：`quality_v1`（Quality Checklist，199 个图片字段）与 `social_audit_v1`（Social Audit Checklist，36 个预留图片字段）。同一工厂项目可在两个清单间切换，共享图库、图片向量和 OCR；每份清单分别匹配、确认、学习并导出 `.xlsx`。

## 启动

1. 设置 `DASHSCOPE_API_KEY`（也可以设置 `AUTOPICK_DEMO_EMBEDDINGS=1` 进行离线演示）。
2. 安装 Python 依赖：`python -m pip install -r requirements.txt`。
3. 在 `frontend` 执行 `pnpm install`，开发时执行 `pnpm run dev`。
4. 后端执行 `python -m backend.run`；生产构建执行 `pnpm run build`。

## 清单与导出

`resources/checklists/quality_v1/Quality list.xlsx` 与 `resources/checklists/social_audit_v1/Social Audit Checklist.xlsx` 是随仓库分发的固定模板，启动时会校验 SHA-256。系统保留工作表、合并单元格、列宽、行高和样式；每个字段只插入一张图片，且只写入模板预留的图片区。输出文件保存在项目的 `outputs/`，命名为 `<工厂名>__<清单类型>__<时间>.xlsx`。缺图会留空并在导出提示中显示数量。

目前支持 `quality_v1` 与 `social_audit_v1`。新增类型时，需要同时提供模板、坐标解析规则和独立偏好配置。

## 数据目录

默认数据目录是开发目录下的 `AutoPickData/`，打包版是 `%LOCALAPPDATA%/AutoPickData/`。每个项目使用稳定 UUID 文件夹：

```text
projects/<project-uuid>/
├─ project.sqlite                 # 项目照片、向量、OCR、匹配和确认记录
├─ project-info.json              # 工厂名、清单类型和目录说明
├─ originals/<photo_id>__<name>   # 项目自己的原图副本
├─ derived/embedding/             # 向量化用派生图
├─ derived/ocr/                   # OCR 用派生图
├─ templates/<checklist-type>.xlsx # 项目使用的只读清单副本
└─ outputs/                       # 导出的 Excel 清单
```

向量实际保存在 `project.sqlite` 的 `embeddings` 表中，通过 `photo_id` 与照片关联。清空当前项目图库只删除项目副本、派生图、向量、OCR、候选和未汇总反馈，不访问外部源图库，也不删除清单模板、Excel 输出或已汇总的别名/偏好。

别名来自用户在某个字段中实际使用的搜索词，以及从历史最终报告中确认的高置信度字段描述。它们按清单类型和字段写入本机全局数据库，并在下一次重新匹配同类字段时追加到检索词中。每次导出会保存字段、系统推荐和最终选图的快照；导入用户修改后的 Excel 时，保留图片记为正确，删除图片记为错误。反馈数据仅保存在用户本机，不随 GitHub 仓库分发。

## 选图约束

自动确认遵循“一图一字段”：同一张照片只能在同一份清单中自动分配给一个字段。若多个字段竞争同一张照片，系统优先保留总匹配分更高的字段，其他字段继续选择下一候选图；没有合适候选时留空。不同清单之间以及人工确认都允许复用图片，用于同一证据支持不同审核维度的情形。

右侧面板会汇总本机所有项目中当前清单类型的人工反馈和有效历史报告样本，并显示训练数据准备度。默认累计到 500 条时提示“请接入训练模型”；可通过 `AUTOPICK_TRAINING_FEEDBACK_THRESHOLD` 调整阈值。该提示只标记产品后半段的接入时机，当前版本不会自动训练模型。

## 隐私

启用真实千问服务时，只有图片和清单文字的向量化会发送到配置的 DashScope/Qwen 接口。图库文字由 RapidOCR 的本地 ONNX 模型识别，不会因 OCR 上传图片；原图、向量、OCR 文本和偏好默认只保存在本机数据目录。OCR 完成后点击“重新匹配清单”，系统会按语义 62%、OCR 文字命中 28%、图片质量 10% 重新排序。
