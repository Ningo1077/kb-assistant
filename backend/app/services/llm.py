"""Prompt 组装与流式生成。provider 可切 mock / ollama / openai，接口层无需改动。"""

import json
import re
from collections.abc import Iterator

import httpx

from ..core.config import settings

SYSTEM_PROMPT = (
    "你是严谨的资料问答助手。请严格遵守以下规则：\n"
    "1. 只依据本轮提供的编号片段回答，不得使用片段之外的知识，不得编造或推测；"
    "片段里没有写的就不要写，也不要为了凑条目补充常识性内容。\n"
    "2. 每轮都必须依据本轮片段重新独立作答：历史对话只用于理解提问中的指代，"
    "不得把历史回答当作答案或缩写模板，也不要因为历史答过类似问题就照抄或简化本轮答案。\n"
    "3. 完整覆盖片段中与问题直接相关的所有信息点：星期与日期、起止时段、金额与数量、"
    "适用条件、例外与补充规定，不得只摘取其中一部分。\n"
    "4. 当问题带有「详细 / 具体 / 全部 / 完整 / 展开 / 有哪些」等要求时，"
    "先给直接答案，再分条列出片段中同一主题下的其它条款（例如问工作时间时，"
    "还要列出弹性打卡、迟到、加班等原文确实存在的规定）；每条都要有片段原文依据。\n"
    "5. 每一条结论后面都必须用 [编号] 标注出处，编号必须来自片段且与该结论对应，"
    "不要给整段话只标一个编号，也不要张冠李戴。\n"
    "6. 如果片段中没有答案，只回复一句话：资料中未提及该信息。\n"
    "7. 使用简体中文，先给结论再给依据，控制在 300 字以内。\n"
    "8. 把直接回答问题的关键信息用 **双星号加粗** 标出，例如：年假为 **15 天**[1]。"
)


def build_context(snippets: list[dict]) -> str:
    blocks = []
    for s in snippets:
        blocks.append(
            f"【片段 {s['index']}】来源：{s['filename']}（第 {s['page_no']} 页）\n{s['content']}"
        )
    return "\n\n".join(blocks)


def build_messages(question: str, snippets: list[dict], history: list[tuple[str, str]]) -> list[dict]:
    """组装本轮消息。

    历史只保留用户提问（最近 3 条），以「历史提问」的形式附在本轮用户消息里，
    不把历史 assistant 回答作为独立消息传入：小参数模型极易把上一轮答案当作模板
    照抄，导致后续提问被缩写成同样的短答案、漏掉星期/条件等关键信息。
    RAG 每轮都会重新检索，历史答案本就不该作为作答依据，仅用于理解指代。
    """
    context = build_context(snippets)
    q = question.strip()
    prior = [
        text.strip()
        for role, text in history
        if role == "user" and text.strip() and text.strip() != q
    ][-3:]
    note = (
        "【历史提问（仅供理解指代，不作为答案依据）】\n" + "\n".join(prior) + "\n\n"
        if prior
        else ""
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{note}【资料片段】\n{context}\n\n【问题】\n{question}",
        },
    ]


def stream_answer(messages: list[dict]) -> Iterator[str]:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        yield from _stream_mock(messages)
    elif provider == "ollama":
        yield from _stream_ollama(messages)
    elif provider == "openai":
        yield from _stream_openai(messages)
    else:
        raise ValueError(f"未知的 LLM_PROVIDER: {settings.llm_provider}")


def _stream_mock(messages: list[dict]) -> Iterator[str]:
    """不依赖任何模型的假回答，用来验证链路是否通畅。"""
    user_content = messages[-1]["content"] if messages else ""
    match = re.search(r"【片段 1】[^\n]*\n(.{0,120})", user_content, re.S)
    excerpt = match.group(1).strip().replace("\n", " ") if match else ""
    if not excerpt:
        yield "资料中未提及该信息。"
        return
    for piece in ["（离线模拟回答，未调用大模型）", "根据资料：", excerpt, "……[1]"]:
        yield piece


def _stream_ollama(messages: list[dict]) -> Iterator[str]:
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": True,
        # 3B 级本地模型在 RAG 场景下需要确定性输出：温度 0.1 时会出现
        # 漏标引用、只摘半句、偶发编造等随机波动，贪心解码明显更稳。
        "options": {"temperature": 0.0, "num_ctx": 8192},
    }
    with httpx.Client(timeout=httpx.Timeout(10.0, read=300.0)) as client:
        with client.stream("POST", f"{settings.llm_base_url.rstrip('/')}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("message", {}).get("content"):
                    yield data["message"]["content"]
                if data.get("done"):
                    break


def _stream_openai(messages: list[dict]) -> Iterator[str]:
    base = settings.llm_base_url.rstrip("/")
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": True,
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    with httpx.Client(timeout=httpx.Timeout(10.0, read=300.0)) as client:
        with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                data = json.loads(chunk)
                delta = data["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta
