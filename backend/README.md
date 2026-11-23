# 私有文档知识库问答助手（后端）

FastAPI + SQLAlchemy 2.0 + PostgreSQL(pgvector) 实现的 RAG 服务：文档入库 → 混合检索 → 流式问答 → 引用溯源。

## 快速开始

环境：Python 3.11+（已在 3.14.6 验证）。

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health
- 端到端自测：`.venv/Scripts/python.exe scripts/smoke_test.py`（TestClient 进程内运行，无需先启服务）

默认配置无需任何外部服务即可跑通（SQLite + 确定性哈希向量 + 模拟回答），用于验证链路。

**安全默认**：启动时会检查 `JWT_SECRET`，若为空或仍是示例值，自动生成随机密钥写入
`data/secret.key`（已加入 `.gitignore`）。多实例部署务必在 `.env` 显式配置同一个密钥，
否则各实例签发的 token 互不认。`CORS_ORIGINS` 默认只允许本机 Vite 与 Tauri 来源，
需要额外前端地址时用逗号分隔填入。

## 切换到 PostgreSQL + pgvector

1. 安装 PostgreSQL 16/17，建库 `kb_assistant`
2. 安装扩展：`CREATE EXTENSION vector;` `CREATE EXTENSION pg_trgm;`
3. 改 `.env`：

```env
DATABASE_URL=postgresql+psycopg://postgres:你的密码@localhost:5432/kb_assistant
```

启动时会自动建表并创建 HNSW 索引（`idx_chunks_embedding_hnsw`）。

## 切换到本地模型（Ollama）

先在目标机器安装 Ollama，把 `OLLAMA_MODELS` 指向你希望存放模型的目录（避免默认落到系统盘），
再拉取 `qwen2.5:3b`（对话）与 `bge-m3`（向量化）。核显 / 16GB 内存的机器 3B 比 7B 稳得多；
换更大模型需同步改 `LLM_MODEL` 并重新 pull。

```env
EMBED_PROVIDER=ollama
EMBED_MODEL=bge-m3
EMBED_DIM=1024        # 必须与模型维度一致，bge-m3 是 1024

LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
LLM_BASE_URL=http://127.0.0.1:11434
```

切换步骤（顺序不能错）：

1. 起服务并拉模型：`ollama serve`，`ollama pull qwen2.5:3b` 与 `ollama pull bge-m3`。
   Windows 上若以服务方式启动，服务进程不会继承当前 shell 的 `OLLAMA_MODELS`，
   建议写一个启动脚本显式设置该环境变量后重启服务。
2. 改 `.env`：开发版 `kb-assistant/backend/.env` 和桌面端已安装版
   `<安装目录>/backend/.env` **两份都要改**（桌面端连的是已安装版后端）。
3. **重启后端**：`settings` 与 `get_embedder` 都有 `lru_cache`，改 .env 不重启不生效。
4. **重建全部文档索引**：
   `.venv/Scripts/python.exe scripts/reindex_all.py`
   （重建已安装版数据库时，把它的 backend 目录作为参数传入，例如
   `.venv/Scripts/python.exe scripts/reindex_all.py "<安装目录>/backend"`）。
   旧向量是 512 维哈希值、新的是 1024 维语义向量，混用会让 SQLite 检索直接报
   形状不匹配；脚本会逐文档重跑解析 → 分块 → 向量化。
5. 验证：`/api/chat` 的 delta 不再包含「离线模拟回答」。

> 限制：`OllamaEmbedder` / `OpenAIEmbedder` 和 LLM 共用同一个 `LLM_BASE_URL`，
> 不能把对话模型与向量模型指向两个不同服务（要拆开需改 `embeddings.py`）。

换成 DeepSeek 等云端服务，或 LM Studio / llama.cpp / vLLM 等本地 OpenAI 兼容服务时，
把 `LLM_PROVIDER` / `EMBED_PROVIDER` 设为 `openai`，`LLM_BASE_URL` 指向对应的
`/v1` 地址并填 `LLM_API_KEY`（本地服务一般不校验 key，随便填即可）。

## 目录结构

```
app/
  main.py            FastAPI 入口、CORS、路由注册
  db.py              引擎/会话/建表/HNSW 索引
  models.py          7 张表 + VectorType（pgvector / SQLite 双兼容）
  schemas.py         Pydantic 出入参
  core/config.py     .env 配置、JWT 密钥解析、CORS 白名单
  core/security.py   PBKDF2 密码哈希 + JWT
  api/auth.py        注册 / 登录 / 当前用户
  api/kb.py          知识库 CRUD
  api/documents.py   上传 / 列表 / 重索引 / 删除
  api/chat.py        SSE 流式问答 / 会话 / 消息 / 反馈
  services/text.py       解析 + 清洗 + 分块
  services/embeddings.py 向量化（hashing / ollama / openai）
  services/ingest.py     入库管线与状态机
  services/retrieval.py  混合检索 + RRF 融合
  services/llm.py        Prompt 组装 + 流式生成
scripts/
  smoke_test.py       端到端自测（TestClient）
  reindex_all.py      换 embedding 后重建全部索引
  make_seed_db.py     生成安装包用的空白数据库（0 行数据）
  prepare-backend.bat 打包前创建/安装后端 venv
```

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | 注册，返回 token |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/auth/me` | 当前用户 |
| GET/POST | `/api/kbs` | 知识库列表 / 创建 |
| GET/DELETE | `/api/kbs/{id}` | 详情 / 删除 |
| GET/POST | `/api/kbs/{id}/documents` | 文档列表 / 上传（multipart） |
| POST | `/api/kbs/{id}/documents/{doc_id}/reindex` | 重新解析入库 |
| POST | `/api/chat` | 流式问答（text/event-stream） |
| GET | `/api/chat/conversations?kb_id=` | 会话列表 |
| GET | `/api/chat/conversations/{id}/messages` | 历史消息（含引用） |
| POST | `/api/chat/feedback` | 回答点赞/点踩 |

### SSE 事件格式

```
data: {"type":"meta","conversation_id":1,"citations":[{"index":1,"filename":"...","page_no":2,"snippet":"..."}]}
data: {"type":"delta","content":"温度"}
data: {"type":"done","message_id":12,"latency_ms":1830,"error":null}
```

前端按 `type` 分发：`meta` 渲染来源列表 → `delta` 追加正文 → `done` 收尾并记下 message_id 供点赞。

## 设计要点（可讲解）

- **双管线**：离线入库一次性完成解析/分块/向量化；在线问答只做检索 + 生成。
- **混合检索**：向量召回 top-20 + 关键词召回 top-20，用 RRF（k=60）融合，解决纯向量对专有名词不敏感的问题。
- **引用溯源**：chunk 带 `page_no`，prompt 要求模型输出 `[n]`，前端把角标映射回片段。
- **秒传去重**：`documents` 表 `(kb_id, sha256)` 唯一约束，同内容文件直接复用已入库的分块。
- **方言兼容**：`VectorType` 在 PostgreSQL 走 pgvector，在 SQLite 退化为 JSON 文本，开发零安装。
- **多轮不串味**：`build_messages` 只把最近 3 条**用户提问**作为「历史提问」附注带进本轮，
  不把历史 assistant 回答作为独立消息传给模型。小参数模型极易把上一轮答案当模板照抄，
  典型症状是「详细工作时间」原样复述「工作时间」、并漏掉星期与例外条件。
  系统提示词同时要求完整覆盖相关信息点、每条结论标注出处、不得编造凑条目；
  本地 3B 模型用 `temperature=0` 贪心解码，避免随机漏标引用。
