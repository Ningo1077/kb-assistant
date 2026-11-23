# 贡献指南

感谢你愿意改进这个项目。本文覆盖本地开发、测试、文档交付物与提交流程；
只想跑起来看效果的话，直接读 [README.md](README.md) 的「从零开始」即可。

## 1. 环境要求

| 用途 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+（已在 3.14.6 验证） | 后端与脚本；`requirements.txt` 中为下限约束 |
| Node.js | 18+ / npm 9+ | 前端（Vite 6 + React 18） |
| Rust + MSVC Build Tools | stable | **仅桌面端打包需要**；只跑 Web 端可跳过 |
| PostgreSQL 16 + pgvector | 可选 | 不装也能跑，默认 SQLite + 512 维哈希向量 |

## 2. 目录结构

```
backend/     FastAPI 服务：app/{api,core,services}、scripts/、tests/
frontend/    React + TypeScript（Vite）；src/{pages,components}
src-tauri/   Tauri v2 桌面壳（Rust）+ NSIS 安装/卸载脚本
docs/        交付文档 Markdown 源文件 + word/（生成物）+ evidence/（执行日志）+ prototype/
scripts/     md_to_docx.py（md→Word）、source_to_docx.py（源码→Word）
demo-files/  虚构演示数据与生成脚本
```

## 3. 本地开发

```bash
# 后端（端口 8000）
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                          # Windows: Copy-Item .env.example .env
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# 前端（端口 5173，另开终端）
cd frontend
npm install
npm run dev
```

- 默认配置零外部依赖：SQLite + `hashing` 向量 + `mock` 回答，先把链路跑通。
- 切真实模型（Ollama / OpenAI 兼容）见 [backend/README.md](backend/README.md)；注意
  `EMBED_PROVIDER=ollama` 时 `EMBED_DIM` 必须同步改成 1024，改完重启后端并跑
  `scripts/reindex_all.py` 重建索引，否则向量形状不匹配会直接报错。
- 桌面端调试：项目根目录执行 `frontend/node_modules/.bin/tauri dev`。

## 4. 测试：提交前必须与 CI 对齐

CI（`.github/workflows/ci.yml`）跑的就是下面这几条，本地同样命令通过即可放心提 PR：

```bash
# ① 39 个单元与接口用例（临时隔离数据库，不污染开发数据）
cd backend && .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" -v

# ② 端到端冒烟：注册 / 登录 / 建库 / 上传 / 检索 / SSE 问答 / 会话
cd backend && .venv/Scripts/python.exe scripts/smoke_test.py

# ③ 空种子库生成器（安装包内置的空库由它产出）
cd backend && .venv/Scripts/python.exe scripts/make_seed_db.py /tmp/kb-seed.db

# ④ 前端类型检查 + 生产构建
cd frontend && npm run build
```

> 冒烟脚本会读取 `backend/.env`。若本机 `.env` 指向 Ollama 而服务没起，
> 上传会因连接被拒而失败——先启动 Ollama，或临时用
> `EMBED_PROVIDER=hashing LLM_PROVIDER=mock` 覆盖后再跑。

新增接口或修 bug 时请补对应用例（`backend/tests/test_all.py` 按类分组），
并同步 `docs/03-测试报告.md` 里的用例数与结论。

## 5. 交付文档（Word）改动规则

`docs/*.md`、`README.md`、`backend/README.md` 是可编辑源文件，
`docs/word/*.docx` 是**生成物**，不要手改 docx：

```bash
# 改完 md 后重新生成 12 份 docx，并回读校验（标题/表格/代码块/正文逐行覆盖）
backend/.venv/Scripts/python.exe scripts/md_to_docx.py
backend/.venv/Scripts/python.exe scripts/md_to_docx.py --check

# 源码文件有增删/改动时重新汇编《源代码文档》，并校验逐行一致 + 每页行数
backend/.venv/Scripts/python.exe scripts/source_to_docx.py
backend/.venv/Scripts/python.exe scripts/source_to_docx.py --check
```

两条命令都以 `CHECK_RESULT=PASS` / `CONVERT_RESULT=PASS` 收尾才算通过。
新增**手写源码/配置**文件时，记得把它加进 `scripts/source_to_docx.py` 的 `GROUPS`，
并同步 README 中的「N 个文件 / M 行」口径（当前 52 个文件 / 6122 行）。

## 6. 提交与分支

- 分支：`main` 为稳定分支（受保护），功能/修复请开 `feat/<简述>`、`fix/<简述>`、`docs/<简述>`。
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：
  `feat: 新增分块重排接口`、`fix: 修复中文文件名下载乱码`、`docs: 补充部署排障`。
- 一个提交只做一件事；不要混入格式化整文件的噪音 diff。

## 7. Pull Request 检查清单

- [ ] 本地跑通第 4 节四条命令（39 用例 / 冒烟 / 种子库 / 前端构建）
- [ ] 涉及 `docs/*.md` 或 README 的改动已重新生成 docx 并通过 `--check`
- [ ] 新增接口已补用例，必要时更新 `docs/01` 的接口表
- [ ] 没有提交密钥与运行时数据：`.env`、`backend/data/*.db`、`secret.key`、`uploads/`、`*.bak`
- [ ] 没有提交构建产物：`node_modules/`、`frontend/dist/`、`src-tauri/target/`、`backend/.venv/`
- [ ] 变更说明写清「改了什么 / 为什么 / 怎么验证」

## 8. 代码风格

- Python：4 空格缩进、类型注解、函数保持单一职责；SQLAlchemy 2.0 风格。
- TypeScript：`strict` 已开启，`tsc --noEmit` 必须零报错；组件拆到 `src/components`。
- Rust：`cargo fmt` + `cargo clippy`（打包前跑一次）。
- Markdown：一行一句、表格对齐；中文与英文/数字之间留一个半角空格。

## 9. 安全问题

发现安全缺陷请按 [SECURITY.md](SECURITY.md) 走私密报告，不要开公开 issue。
