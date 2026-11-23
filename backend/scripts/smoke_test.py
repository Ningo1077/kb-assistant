"""端到端冒烟测试：注册 → 登录 → 建库 → 上传 → 入库 → 检索问答。

用 TestClient 在进程内跑，不需要先启动 uvicorn。
    .venv/Scripts/python.exe scripts/smoke_test.py
"""

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = """# 智能家居环境监测系统设计说明

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
    events = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def main() -> int:
    init_db()
    client = TestClient(app)
    email = f"student_{uuid.uuid4().hex[:8]}@example.com"

    print("[1/7] 健康检查")
    health = client.get("/health")
    assert health.status_code == 200, health.text
    print("      ", health.json())

    print("[2/7] 注册")
    reg = client.post("/api/auth/register", json={"email": email, "password": "test123456", "display_name": "演示账号"})
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]

    print("[3/7] 登录")
    login = client.post("/api/auth/login", json={"email": email, "password": "test123456"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    print("[4/7] 创建知识库")
    kb = client.post("/api/kbs", json={"name": "智能家居资料", "description": "演示知识库"}, headers=headers)
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    print("[5/7] 上传文档并入库")
    files = {"file": ("智能家居系统设计说明.md", SAMPLE.encode("utf-8"), "text/markdown")}
    up = client.post(f"/api/kbs/{kb_id}/documents", files=files, headers=headers)
    assert up.status_code == 201, up.text
    # 响应体在后台任务执行前就生成了，这里重新拉一次真实状态
    doc = client.get(f"/api/kbs/{kb_id}/documents/{up.json()['id']}", headers=headers).json()
    assert doc["status"] == "ready", f"入库未完成：{doc}"
    print(f"       状态={doc['status']} 分块数={doc['chunk_count']} 页数={doc['page_count']}")
    assert doc["chunk_count"] > 0

    print("[6/7] 问答（SSE 流式）")
    resp = client.post(
        "/api/chat",
        json={"kb_id": kb_id, "question": "温度超过多少度会触发告警？"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    events = parse_sse(resp.text)
    meta = next((e for e in events if e["type"] == "meta"), None)
    answer = "".join(e.get("content", "") for e in events if e["type"] == "delta")
    done = next((e for e in events if e["type"] == "done"), None)

    assert meta and meta["citations"], "没有返回引用片段，检索链路有问题"
    assert answer.strip(), "回答为空"
    top = meta["citations"][0]
    print(f"       引用[1] = {top['filename']} 第{top['page_no']}页 余弦相似度={top['similarity']}")
    print(f"       回答：{answer[:120]}")
    print(f"       耗时：{done['latency_ms']}ms")

    print("[7/7] 会话落库校验")
    convs = client.get(f"/api/chat/conversations?kb_id={kb_id}", headers=headers).json()
    msgs = client.get(f"/api/chat/conversations/{convs[0]['id']}/messages", headers=headers).json()
    assert len(msgs) == 2, f"应有一问一答两条消息，实际 {len(msgs)}"
    assert msgs[1]["citations"], "助手消息未落库引用"
    print(f"       会话数={len(convs)} 消息数={len(msgs)}")

    print("\n全链路通过：注册/登录/建库/上传/入库/混合检索/流式问答/引用落库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
