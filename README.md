# 私有文档知识库问答助手

课程结课答辩项目（个人作品）。给个人/小团队使用的私有文档问答系统：把 PDF / Word / Markdown 导进知识库，
用自然语言提问，答案必须标注出自哪份文件第几页。

> `demo-files/` 下的 PDF / DOCX / CSV / TXT 均由 `demo-files/gen_demo_files.py` 生成，
> 「云澜科技」等公司、人员与数字全部虚构，不含任何真实信息。

## 技术栈与评分对照

| 要求 | 本项目的实现 | 语言 |
|---|---|---|
| 编程语言 ≥ 2 | 前端 TypeScript / 后端 Python / 桌面端 Rust / 数据库 SQL | 4 种 |
| 前后端分离 | React + Vite ⇄ FastAPI（REST + SSE 流式） | — |
| 数据库 | PostgreSQL 16 + pgvector（开发期 SQLite 兼容） | SQL |
| 作品形态 | Web 端 + **Tauri 桌面客户端**（安装包，+5 分） | — |

## 目录

```
kb-assistant/
├── backend/      FastAPI 服务：文档入库、混合检索、流式问答
├── frontend/     React + TypeScript 前端
├── src-tauri/    Tauri v2 桌面客户端（Rust）+ NSIS 安装/卸载脚本
├── demo-files/   虚构的演示文档与生成脚本
├── docs/         需求分析与技术选型文档
└── LICENSE       MIT
```

## 当前进度

- [x] 数据层：7 张表、pgvector / SQLite 双兼容向量列、HNSW 索引
- [x] 鉴权：PBKDF2 密码哈希 + JWT（默认弱密钥自动替换为本机随机密钥）
- [x] 文档入库管线：解析 → 清洗 → 分块 → 向量化 → 落库，状态机 + 秒传去重
- [x] 混合检索：向量召回 + 关键词召回 + RRF 融合
- [x] SSE 流式问答：引用溯源、会话历史、点赞反馈
- [x] 前端（登录、知识库、上传、聊天、拖拽上传）
- [x] Tauri 桌面客户端：启动自动拉起后端、托盘常驻、Ctrl+Shift+K 全局唤起、文件拖入上传
- [x] 打包：NSIS 安装包（内置后端 + venv + 空白 SQLite，演示机零依赖）
- [x] 卸载：询问是否保留知识库数据，按安装路径精确结束进程并备份
- [x] 打包数据隔离：安装包不携带开发机的 `.env`、数据库、上传文档与备份文件
- [ ] 答辩 PPT / 演示脚本

## 从零开始（clone 后第一步）

环境要求：Python 3.11+（已在 3.14.6 验证）、Node.js 18+ / npm。
桌面端**打包**另需 Rust 与 Visual Studio Build Tools（MSVC 链接器），仅开发/运行 Web 端不需要。

```bash
# 1) 后端
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                          # Windows: Copy-Item .env.example .env
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# 2) 前端（另开一个终端）
cd frontend
npm install
npm run dev                                                   # http://localhost:5173
```

- Swagger 文档：http://127.0.0.1:8000/docs ；健康检查：`/health`
- 端到端自测：`.venv/Scripts/python.exe scripts/smoke_test.py`（TestClient 进程内跑，无需先启服务）
- 默认配置零外部依赖：SQLite + 512 维确定性哈希向量 + 模拟回答，先把链路跑通。
- 首次启动会自动在 `backend/data/secret.key` 生成随机 JWT 密钥（已被 `.gitignore` 忽略）。
  多机/多进程部署请在 `.env` 显式配置同一个 `JWT_SECRET`。

### 接入真实模型

完整步骤见 `backend/README.md` 的「切换到本地模型（Ollama）」。最容易踩的坑：

- `EMBED_PROVIDER` 改为 `ollama` 时，`EMBED_DIM` **必须同步改成 1024**（bge-m3 是 1024 维）；
- 改完要**重启后端**（`settings` / `get_embedder` 有 `lru_cache`），
  再运行 `.venv/Scripts/python.exe scripts/reindex_all.py` **重建全部文档索引**；
- 512 维哈希向量与 1024 维语义向量混用会让 SQLite 检索直接报形状不匹配。

## 桌面客户端

打包前先准备后端 venv（安装包会内置它）：

```bash
backend\scripts\prepare-backend.bat
```

然后在**项目根目录 `kb-assistant/`** 执行（`tauri` CLI 在其它目录找不到 `src-tauri/tauri.conf.json`）：

```bash
frontend/node_modules/.bin/tauri build
```

兜底方案：无 MSVC 链接器时，复用已编译 exe 与缓存的 NSIS 工具链重打安装包 —— `src-tauri/nsis/build-setup.cmd`。

产物输出到 `src-tauri/target/release/bundle/nsis/KB-Assistant_<VERSION>_x64-setup.exe`
（版本号由 `tauri.conf.json` 的 `version` 与 `setup.nsi` 的 `!define VERSION` 决定，发版时同步更新）。

> **打包数据隔离**：`tauri.conf.json` 的 `resources` 与 `setup.nsi` 都使用显式白名单，
> 只复制 `backend/app`、`backend/scripts`、`requirements.txt`、`.env.example`、`.venv` 和卸载脚本，
> **不会**把开发机的 `.env`、`data/app.db`、`uploads/`、`*.bak` 打进安装包。
> 空库由 `backend/scripts/make_seed_db.py` 生成（7 张表、0 行数据），首次启动自动建表。
>
> 推荐标准打包：产物由 Tauri 官方 NSIS 模板生成，自带 WebView2 引导检测，
> `windows/hooks.nsh` 卸载钩子会自动生效；兜底脚本产出的包不含 WebView2 引导检测。

- 桌面端默认 SQLite；恢复 PostgreSQL 只需改 `.env` 的 `DATABASE_URL`。
- 安装包内置 `.venv`，其 `pyvenv.cfg` 指向打包机的基础解释器路径；
  换到没有该 Python 的机器上运行 `prepare-backend.bat` 重建 venv 即可。
- 快捷键 `Ctrl+Shift+K` 全局唤起/隐藏窗口；关闭按钮最小化到托盘。

### 卸载程序

安装包自带 NSIS 卸载器，可通过「设置 → 应用 → 已安装的应用」、开始菜单的
`Uninstall KB-Assistant`，或安装目录下的 `uninstall.exe` 卸载（静默：`uninstall.exe /S`）。

卸载逻辑放在 `src-tauri/windows/`：

- `uninstall-cleanup.ps1`：卸载前结束托盘主程序与本应用拉起的后端 python
  （按安装路径 + `app.main:app` 精确匹配，不误杀其它 Python 进程），并按需把
  `backend/data`（数据库、上传文档）备份到 `文档\KB-Assistant-Backup\<时间戳>`；
  备份根目录可用环境变量 `KB_BACKUP_ROOT` 覆盖。
- `hooks.nsh`：标准 `tauri build` 使用的 NSIS 卸载钩子，交互卸载时询问是否保留数据，
  静默卸载默认保留数据。
- `nsis/setup.nsi` + `nsis/build-setup.cmd`：独立安装/卸载脚本与一键重打包命令，
  作为无 MSVC 链接器机器的兜底方案。

## 安全说明

- **JWT**：`.env` / `.env.example` 中的示例密钥会被自动识别并替换为本机随机密钥
  （`backend/data/secret.key`，不入库）。生成后旧 token 失效，重新登录一次即可。
- **CORS**：默认只允许 localhost / 127.0.0.1 / Tauri 来源，可用 `CORS_ORIGINS` 覆盖；
  不再使用 `allow_origins=["*"]`。
- 本项目定位为本机 / 局域网单机使用。若要公网部署，请自行补充 TLS、速率限制、
  注册管控与上传内容扫描。

## 许可

[MIT](LICENSE) © 2026 Ningo1077
