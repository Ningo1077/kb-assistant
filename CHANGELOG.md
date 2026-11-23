# 更新日志

本项目的所有重要变更都记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 计划中

- 真实模型（Ollama / OpenAI 兼容）下的完整评测数据补录

## [1.0.0] - 2026-11-23

首个完整可用版本：Web 端 + Tauri 桌面客户端，私有文档问答全链路闭环。

### Added

- 数据层：7 张表（用户 / 知识库 / 文档 / 分块 / 会话 / 消息 / 反馈），
  pgvector 与 SQLite 双兼容向量列，PostgreSQL 侧 HNSW 索引。
- 鉴权：PBKDF2 密码哈希 + JWT；示例弱密钥自动替换为本机随机密钥（`backend/data/secret.key`）。
- 文档入库管线：解析 → 清洗 → 分块 → 向量化 → 落库，状态机 + 秒传去重，支持 PDF / DOCX / Markdown / TXT / CSV。
- 混合检索：向量召回 + 关键词召回 + RRF 融合，引用带文件名与页码溯源。
- 问答接口：SSE 流式输出、会话历史、点赞反馈。
- 前端：登录、知识库管理、拖拽上传、聊天面板（React 18 + TypeScript + Vite）。
- 桌面端：Tauri v2 客户端，启动自动拉起内置后端、托盘常驻、`Ctrl+Shift+K` 全局唤起、文件拖入上传。
- 打包：NSIS 安装包（内置后端 venv + 空白 SQLite），卸载时按需备份知识库数据。
- 测试：39 个单元与接口自动化用例（`backend/tests/test_all.py`），临时隔离数据库。
- CI：GitHub Actions 双作业（后端测试 / 冒烟 / 种子库生成 + 前端类型检查与构建）。
- 交付文档：12 份 Word 文档（需求分析、设计说明书、UI 原型、测试报告、部署手册、使用说明书、源代码文档），
  由 `scripts/md_to_docx.py` / `scripts/source_to_docx.py` 生成并回读校验。

### Security

- CORS 默认仅允许 localhost / 127.0.0.1 / Tauri 来源，不再使用 `*`。
- 打包白名单化：安装包不携带开发机 `.env`、`data/*.db`、`uploads/` 与备份文件。
