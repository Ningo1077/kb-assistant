"""自动化测试用例集（标准库 unittest，无需额外安装 pytest）。

从 backend/ 目录运行：
    .venv/Scripts/python.exe -m unittest discover -s tests -v
    # macOS / Linux: .venv/bin/python -m unittest discover -s tests -v

设计要点：在导入任何 app 模块之前，用环境变量把数据库、上传目录与 JWT 密钥
重定向到临时目录，保证测试不会读写开发机的 backend/data/app.db 与 secret.key。
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

# ── 必须在 import app.* 之前完成测试环境隔离 ──────────────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="kb-assistant-test-"))
os.environ["DATABASE_URL"] = "sqlite:///" + (_TMP / "test.db").as_posix()
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["JWT_SECRET"] = "test-only-fixed-secret-do-not-use-in-production-2026"
os.environ["EMBED_PROVIDER"] = "hashing"
os.environ["EMBED_DIM"] = "512"
os.environ["LLM_PROVIDER"] = "mock"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import (  # noqa: E402
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.embeddings import HashingEmbedder, embed_texts  # noqa: E402
from app.services.ingest import file_sha256, validate_upload  # noqa: E402
from app.services.llm import SYSTEM_PROMPT, build_context, build_messages  # noqa: E402
from app.services.text import (  # noqa: E402
    Segment,
    chunk_segments,
    clean_text,
    parse_document,
)

SAMPLE_MD = """# 智能家居环境监测系统设计说明

## 一、总体架构
系统由感知层、网关层、服务层与应用层四部分组成。感知层使用 ESP32 采集温湿度数据，
通过 MQTT 协议上报至局域网内的 Mosquitto 消息代理，采样周期为 5 秒。

## 二、告警策略
当室内温度连续 3 个采样点超过 35 摄氏度时触发高温告警；当相对湿度低于 20% 时触发干燥告警。
告警信息通过企业微信机器人推送给管理员，并在大屏上以红色卡片展示。

## 三、数据存储
历史数据写入时序数据库 InfluxDB，保留策略为 90 天。设备上下线记录写入 PostgreSQL，
用于统计设备在线率。

## 四、异常处理
网关与服务端之间使用 WebSocket 保持长连接，断线后按 1s、2s、4s、8s 做指数退避重连，
最多重试 5 次。若仍失败则降级为 60 秒轮询，并在日志中记录 NET_RETRY_EXCEEDED。
"""


def parse_sse(raw: str) -> list[dict]:
    return [
        json.loads(line[5:].strip())
        for line in raw.splitlines()
        if line.startswith("data:")
    ]


def new_email() -> str:
    return f"case_{uuid.uuid4().hex[:12]}@example.com"


def tearDownModule() -> None:
    """释放 SQLAlchemy 连接池，避免解释器退出时报未关闭的 sqlite 连接。"""
    from app.db import engine

    engine.dispose()


class TestTextService(unittest.TestCase):
    """TC-TXT-01~06：文档解析、清洗与分块。"""

    def test_01_clean_text_removes_isolated_page_number(self):
        out = clean_text("第一段正文。\n12\n第二段正文。")
        self.assertNotIn("\n12\n", out)
        self.assertIn("第一段正文", out)
        self.assertIn("第二段正文", out)

    def test_02_clean_text_removes_page_footer(self):
        out = clean_text("正文内容。\n第 3 页 / 共 20 页\n下一段内容。")
        self.assertIn("正文内容", out)
        self.assertIn("下一段内容", out)
        self.assertNotIn("共 20 页", out)

    def test_03_clean_text_merges_pdf_hard_wrap(self):
        out = clean_text("感知层使用 ESP32 采集温湿度数据，\n通过 MQTT 协议上报至消息代理。")
        self.assertIn("采集温湿度数据，通过 MQTT", out)

    def test_04_parse_document_rejects_unsupported_type(self):
        p = _TMP / "unsupported.exe"
        p.write_bytes(b"MZ")
        with self.assertRaises(ValueError) as ctx:
            parse_document(p)
        self.assertIn("不支持的文件类型", str(ctx.exception))

    def test_05_parse_markdown_keeps_page_one(self):
        p = _TMP / "sample.md"
        p.write_text(SAMPLE_MD, encoding="utf-8")
        segments = parse_document(p)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].page_no, 1)
        self.assertIn("告警策略", segments[0].text)

    def test_06_chunk_segments_has_continuous_index_and_overlap(self):
        long_text = "".join(
            f"第{i}条规定了设备在第{i}种异常场景下的处置流程，需要记录日志并通知管理员。" for i in range(1, 60)
        )
        pieces = chunk_segments([Segment(page_no=3, text=long_text)], size=300, overlap=60)
        self.assertGreater(len(pieces), 1)
        self.assertEqual([p.index for p in pieces], list(range(len(pieces))))
        self.assertTrue(all(p.page_no == 3 for p in pieces))
        self.assertTrue(all(len(p.content) >= 30 for p in pieces))
        # 相邻块之间应存在重叠内容（尾句被带入下一块开头）
        self.assertTrue(any(p.content[:10] in pieces[i - 1].content for i, p in enumerate(pieces) if i > 0))


class TestEmbeddingAndRetrieval(unittest.TestCase):
    """TC-EMB-01~06：向量化、批处理、关键词提取、RRF 融合、Prompt 组装。"""

    def test_01_hash_embedding_dim_and_normalization(self):
        e = HashingEmbedder(512)
        vec = e.embed(["温湿度采集与告警策略"])[0]
        self.assertEqual(len(vec), 512)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in vec)), 1.0, places=5)

    def test_02_hash_embedding_is_deterministic(self):
        e = HashingEmbedder(512)
        a = e.embed(["室内温度超过 35 摄氏度"])[0]
        b = e.embed(["室内温度超过 35 摄氏度"])[0]
        c = e.embed(["完全不同的另一段文字"])[0]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_03_embed_texts_batches_over_16_items(self):
        vecs = embed_texts([f"第{i}条测试文本" for i in range(37)], batch_size=16)
        self.assertEqual(len(vecs), 37)
        self.assertTrue(all(len(v) == 512 for v in vecs))

    def test_04_terms_extracts_cjk_bigrams_and_latin_words(self):
        terms = retrieval._terms("ESP32 温度超过多少度会触发告警？")
        self.assertIn("esp32", terms)
        self.assertTrue(any("温度" == t or "温度" in t for t in terms))
        self.assertLessEqual(len(terms), 6)

    def test_05_rrf_fusion_merges_two_recall_channels(self):
        # 借用 API 测试写入的数据前，先自建最小数据集，保证本用例独立可跑
        from app.models import Chunk, Document, KnowledgeBase, User

        db = SessionLocal()
        try:
            email = new_email()
            user = User(email=email, password_hash=hash_password("test123456"))
            db.add(user)
            db.commit()
            kb = KnowledgeBase(owner_id=user.id, name="RRF 用例库")
            db.add(kb)
            db.commit()
            doc = Document(
                kb_id=kb.id,
                filename="rrf.md",
                sha256=uuid.uuid4().hex,
                status="ready",
            )
            db.add(doc)
            db.commit()
            vecs = embed_texts(["室内温度连续 3 个采样点超过 35 摄氏度时触发高温告警"])
            db.add(
                Chunk(
                    doc_id=doc.id,
                    kb_id=kb.id,
                    content="室内温度连续 3 个采样点超过 35 摄氏度时触发高温告警",
                    page_no=1,
                    embedding=vecs[0],
                )
            )
            db.commit()
            hits = retrieval.retrieve(db, kb.id, "温度超过多少度会触发告警")
            self.assertTrue(hits, "混合检索应至少返回 1 个命中")
            self.assertIsNotNone(hits[0].vector_rank)
            self.assertIsNotNone(hits[0].keyword_rank, "两路召回应融合到同一 chunk")
            self.assertEqual(round(hits[0].score, 4), 1.0, "归一化后首位得分应为 1.0")
        finally:
            db.close()

    def test_06_prompt_contains_grounding_and_refusal_rules(self):
        snippets = [{"index": 1, "filename": "手册.pdf", "page_no": 2, "content": "年假为 15 天。"}]
        messages = build_messages(
            "年假有几天？",
            snippets,
            [("user", "年假有几天？"), ("assistant", "上一轮错误回答：42 天")],
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("不得编造", SYSTEM_PROMPT)
        self.assertIn("资料中未提及该信息", SYSTEM_PROMPT)
        self.assertIn("[编号]", SYSTEM_PROMPT)
        self.assertIn("【片段 1】", build_context(snippets))
        # 历史 assistant 回答不得作为独立消息传入，也不能混进本轮上下文
        self.assertNotIn("上一轮错误回答", messages[1]["content"])
        self.assertEqual(len([m for m in messages if m["role"] == "assistant"]), 0)

    def test_07_mock_llm_refuses_when_no_context(self):
        from app.services.llm import stream_answer

        answer = "".join(stream_answer([{"role": "user", "content": "【资料片段】\n\n【问题】\n年假几天"}]))
        self.assertEqual(answer, "资料中未提及该信息。")


class TestSecurity(unittest.TestCase):
    """TC-SEC-01~05：口令散列、JWT、上传校验。"""

    def test_01_password_hash_is_salted_and_not_plaintext(self):
        h1 = hash_password("test123456")
        h2 = hash_password("test123456")
        self.assertNotIn("test123456", h1)
        self.assertTrue(h1.startswith("pbkdf2_sha256$260000$"))
        self.assertNotEqual(h1, h2, "相同口令两次散列必须不同（随机盐）")

    def test_02_verify_password_handles_wrong_and_malformed(self):
        h = hash_password("test123456")
        self.assertTrue(verify_password("test123456", h))
        self.assertFalse(verify_password("wrong-password", h))
        self.assertFalse(verify_password("test123456", "not-a-valid-hash"))

    def test_03_jwt_roundtrip_and_tamper_detection(self):
        token = create_access_token(42, "student@example.com")
        payload = decode_token(token)
        self.assertEqual(payload["sub"], "42")
        self.assertEqual(payload["email"], "student@example.com")
        self.assertIn("exp", payload)
        import jwt

        with self.assertRaises(jwt.PyJWTError):
            jwt.decode(token, "another-secret-that-is-long-enough-for-hs256", algorithms=["HS256"])

    def test_04_validate_upload_rules(self):
        self.assertEqual(validate_upload("a.PDF", 10), ".pdf")
        for name, size, keyword in [
            ("a.exe", 10, "仅支持"),
            ("a.pdf", 21 * 1024 * 1024, "超过"),
            ("a.pdf", 0, "为空"),
        ]:
            with self.assertRaises(ValueError) as ctx:
                validate_upload(name, size)
            self.assertIn(keyword, str(ctx.exception))

    def test_05_sha256_is_stable(self):
        p = _TMP / "sha.md"
        p.write_bytes(SAMPLE_MD.encode("utf-8"))
        self.assertEqual(len(file_sha256(p)), 64)
        self.assertEqual(file_sha256(p), file_sha256(p))


class TestApiFlow(unittest.TestCase):
    """TC-API-01~12：注册登录、知识库、文档入库、问答、会话、反馈全链路。"""

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.email = new_email()
        cls.headers: dict[str, str] = {}
        cls.kb_id: int = 0
        cls.doc_id: int = 0
        cls.conv_id: int = 0
        cls.message_id: int = 0

    def test_01_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "sqlite")
        self.assertEqual(body["embed_provider"], "hashing")
        self.assertEqual(body["llm_provider"], "mock")

    def test_02_register(self):
        r = self.client.post(
            "/api/auth/register",
            json={"email": self.email, "password": "test123456", "display_name": "测试账号"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json()["access_token"])
        self.assertEqual(r.json()["user"]["email"], self.email)

    def test_03_duplicate_register_conflict(self):
        r = self.client.post(
            "/api/auth/register", json={"email": self.email, "password": "test123456"}
        )
        self.assertEqual(r.status_code, 409)

    def test_04_login_and_me(self):
        r = self.client.post(
            "/api/auth/login", json={"email": self.email, "password": "test123456"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.__class__.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        me = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], self.email)

    def test_05_wrong_password(self):
        r = self.client.post(
            "/api/auth/login", json={"email": self.email, "password": "bad-password"}
        )
        self.assertEqual(r.status_code, 401)

    def test_06_auth_required(self):
        self.assertEqual(self.client.get("/api/kbs").status_code, 401)
        self.assertEqual(
            self.client.get("/api/kbs", headers={"Authorization": "Bearer forged.token.here"}).status_code,
            401,
        )

    def test_07_input_validation(self):
        cases = [
            ("/api/auth/register", {"email": "not-an-email", "password": "test123456"}),
            ("/api/auth/register", {"email": new_email(), "password": "123"}),
            ("/api/auth/register", {"email": new_email(), "password": "x" * 73}),
        ]
        for path, payload in cases:
            self.assertEqual(self.client.post(path, json=payload).status_code, 422, payload)

    def test_08_kb_crud(self):
        r = self.client.post(
            "/api/kbs", json={"name": "演示知识库", "description": "自动化测试"}, headers=self.headers
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.__class__.kb_id = r.json()["id"]
        listed = self.client.get("/api/kbs", headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(k["id"] == self.kb_id for k in listed.json()))
        detail = self.client.get(f"/api/kbs/{self.kb_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["name"], "演示知识库")

    def test_09_upload_and_ingest(self):
        files = {"file": ("系统设计说明.md", SAMPLE_MD.encode("utf-8"), "text/markdown")}
        r = self.client.post(f"/api/kbs/{self.kb_id}/documents", files=files, headers=self.headers)
        self.assertEqual(r.status_code, 201, r.text)
        self.__class__.doc_id = r.json()["id"]
        doc = self.client.get(
            f"/api/kbs/{self.kb_id}/documents/{self.doc_id}", headers=self.headers
        ).json()
        self.assertEqual(doc["status"], "ready", doc)
        self.assertGreater(doc["chunk_count"], 0)
        self.assertGreaterEqual(doc["page_count"], 1)

    def test_10_dedup_upload_returns_same_document(self):
        files = {"file": ("系统设计说明-副本.md", SAMPLE_MD.encode("utf-8"), "text/markdown")}
        r = self.client.post(f"/api/kbs/{self.kb_id}/documents", files=files, headers=self.headers)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["id"], self.doc_id, "同内容文件应命中秒传，复用已有文档")
        listed = self.client.get(f"/api/kbs/{self.kb_id}/documents", headers=self.headers).json()
        self.assertEqual(len(listed), 1, "秒传不应新增文档记录")

    def test_11_upload_validation_errors(self):
        bad_type = {"file": ("virus.exe", b"MZ", "application/octet-stream")}
        self.assertEqual(
            self.client.post(f"/api/kbs/{self.kb_id}/documents", files=bad_type, headers=self.headers).status_code,
            400,
        )
        empty = {"file": ("empty.md", b"", "text/markdown")}
        self.assertEqual(
            self.client.post(f"/api/kbs/{self.kb_id}/documents", files=empty, headers=self.headers).status_code,
            400,
        )

    def test_12_chat_sse_and_persistence(self):
        started = time.perf_counter()
        r = self.client.post(
            "/api/chat",
            json={"kb_id": self.kb_id, "question": "温度超过多少度会触发告警？"},
            headers=self.headers,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("text/event-stream", r.headers["content-type"])
        events = parse_sse(r.text)
        kinds = [e["type"] for e in events]
        self.assertIn("meta", kinds)
        self.assertIn("delta", kinds)
        self.assertIn("done", kinds)

        meta = next(e for e in events if e["type"] == "meta")
        answer = "".join(e["content"] for e in events if e["type"] == "delta")
        done = next(e for e in events if e["type"] == "done")
        self.assertTrue(meta["citations"], "必须返回引用片段")
        self.assertEqual(meta["citations"][0]["filename"], "系统设计说明.md")
        self.assertGreaterEqual(meta["citations"][0]["page_no"], 1)
        self.assertTrue(answer.strip())
        self.assertIn("[1]", answer)
        self.assertIsNone(done["error"])
        self.__class__.conv_id = meta["conversation_id"]
        self.__class__.message_id = done["message_id"]
        self.assertLess(elapsed_ms, 2000, "mock 模式下端到端问答应在 2s 内完成")

    def test_13_conversation_history_and_messages(self):
        convs = self.client.get(
            f"/api/chat/conversations?kb_id={self.kb_id}", headers=self.headers
        ).json()
        self.assertTrue(any(c["id"] == self.conv_id for c in convs))
        msgs = self.client.get(
            f"/api/chat/conversations/{self.conv_id}/messages", headers=self.headers
        ).json()
        self.assertEqual(len(msgs), 2)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertTrue(msgs[1]["citations"], "助手消息的引用快照必须落库")

    def test_14_multi_turn_reuses_conversation(self):
        r = self.client.post(
            "/api/chat",
            json={
                "kb_id": self.kb_id,
                "question": "采样周期是多少？",
                "conversation_id": self.conv_id,
            },
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200, r.text)
        meta = next(e for e in parse_sse(r.text) if e["type"] == "meta")
        self.assertEqual(meta["conversation_id"], self.conv_id)
        msgs = self.client.get(
            f"/api/chat/conversations/{self.conv_id}/messages", headers=self.headers
        ).json()
        self.assertEqual(len(msgs), 4, "多轮问答应在同一会话内累加")

    def test_15_feedback_and_validation(self):
        r = self.client.post(
            "/api/chat/feedback",
            json={"message_id": self.message_id, "rating": 1, "comment": "引用准确"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json(), {"ok": True})
        self.assertEqual(
            self.client.post(
                "/api/chat/feedback",
                json={"message_id": self.message_id, "rating": 5},
                headers=self.headers,
            ).status_code,
            422,
            "rating 必须在 [-1, 1]",
        )
        self.assertEqual(
            self.client.post(
                "/api/chat/feedback",
                json={"message_id": 999999, "rating": 1},
                headers=self.headers,
            ).status_code,
            404,
        )

    def test_16_reindex_and_delete_document(self):
        r = self.client.post(
            f"/api/kbs/{self.kb_id}/documents/{self.doc_id}/reindex", headers=self.headers
        )
        self.assertEqual(r.status_code, 200, r.text)
        doc = self.client.get(
            f"/api/kbs/{self.kb_id}/documents/{self.doc_id}", headers=self.headers
        ).json()
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(
            self.client.delete(
                f"/api/kbs/{self.kb_id}/documents/{self.doc_id}", headers=self.headers
            ).status_code,
            204,
        )


class TestAuthorization(unittest.TestCase):
    """TC-AUTH-01~05：越权访问一律 404，不泄露资源是否存在。"""

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

        def make_user() -> dict:
            email = new_email()
            reg = cls.client.post(
                "/api/auth/register", json={"email": email, "password": "test123456"}
            )
            return {"Authorization": f"Bearer {reg.json()['access_token']}"}

        cls.a, cls.b = make_user(), make_user()
        cls.kb_id = cls.client.post(
            "/api/kbs", json={"name": "A 的私有知识库"}, headers=cls.a
        ).json()["id"]
        files = {"file": ("private.md", SAMPLE_MD.encode("utf-8"), "text/markdown")}
        cls.doc_id = cls.client.post(
            f"/api/kbs/{cls.kb_id}/documents", files=files, headers=cls.a
        ).json()["id"]
        cls.conv_id = next(
            e
            for e in parse_sse(
                cls.client.post(
                    "/api/chat",
                    json={"kb_id": cls.kb_id, "question": "温度告警阈值？"},
                    headers=cls.a,
                ).text
            )
            if e["type"] == "meta"
        )["conversation_id"]

    def test_01_other_users_kb_is_404(self):
        self.assertEqual(self.client.get(f"/api/kbs/{self.kb_id}", headers=self.b).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/kbs/{self.kb_id}", headers=self.b).status_code, 404)
        self.assertEqual(self.client.get("/api/kbs", headers=self.b).json(), [])

    def test_02_other_users_documents_are_hidden(self):
        self.assertEqual(
            self.client.get(f"/api/kbs/{self.kb_id}/documents", headers=self.b).status_code, 404
        )
        self.assertEqual(
            self.client.delete(
                f"/api/kbs/{self.kb_id}/documents/{self.doc_id}", headers=self.b
            ).status_code,
            404,
        )

    def test_03_chat_cannot_target_others_kb(self):
        self.assertEqual(
            self.client.post(
                "/api/chat",
                json={"kb_id": self.kb_id, "question": "偷看一下"},
                headers=self.b,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/chat/conversations?kb_id={self.kb_id}", headers=self.b
            ).status_code,
            404,
        )

    def test_04_other_users_conversation_is_404(self):
        self.assertEqual(
            self.client.get(
                f"/api/chat/conversations/{self.conv_id}/messages", headers=self.b
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/chat/conversations/{self.conv_id}", headers=self.b
            ).status_code,
            404,
        )

    def test_05_cross_kb_conversation_is_rejected(self):
        other_kb = self.client.post(
            "/api/kbs", json={"name": "A 的另一个库"}, headers=self.a
        ).json()["id"]
        r = self.client.post(
            "/api/chat",
            json={
                "kb_id": other_kb,
                "question": "串库测试",
                "conversation_id": self.conv_id,
            },
            headers=self.a,
        )
        self.assertEqual(r.status_code, 404, r.text)

    @classmethod
    def tearDownClass(cls):
        cls.client.delete(f"/api/kbs/{cls.kb_id}", headers=cls.a)


if __name__ == "__main__":
    unittest.main(verbosity=2)
