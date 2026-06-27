"""
检索脚本。

用法：
    uv run query.py <招标文件.md>
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DB_PATH    = "rag.db"
INDEX_PATH = "chunks.index"
MAP_PATH   = "chunks_map.json"

DIM    = 1024
TOP_K  = 10

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


def load_resources():
    for p in [INDEX_PATH, MAP_PATH, DB_PATH]:
        if not Path(p).exists():
            raise FileNotFoundError(f"文件不存在：{p}，请先运行 build_index.py")
    index = faiss.read_index(INDEX_PATH)
    with open(MAP_PATH, encoding="utf-8") as f:
        chunk_map = json.load(f)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return index, chunk_map, conn


def embed_query(text: str) -> np.ndarray:
    resp = client.embeddings.create(
        model="text-embedding-v4",
        input=[text],
        dimensions=DIM,
        encoding_format="float",
    )
    vec = np.array([resp.data[0].embedding], dtype="float32")
    faiss.normalize_L2(vec)
    return vec


def recall(index, chunk_map: list, conn: sqlite3.Connection, vec: np.ndarray) -> list[dict]:
    k = min(TOP_K, index.ntotal)
    _, indices = index.search(vec, k)
    results = []
    for idx in indices[0]:
        if idx < 0 or idx >= len(chunk_map):
            continue
        chunk_id = chunk_map[idx]
        row = conn.execute(
            "SELECT source_text, section_path FROM chunks WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()
        if row:
            results.append({"source_text": row["source_text"], "section_path": row["section_path"]})
    return results


def build_prompt(question: str, hits: list[dict]) -> str:
    fragments = ""
    for i, h in enumerate(hits, 1):
        fragments += f"[片段{i}] 来源：{h['section_path']}\n{h['source_text']}\n\n"
    return (
        "你是招标文件分析助手。严格基于以下原文片段回答，不得脱离原文。\n"
        "若片段中无相关信息，回答"未找到相关内容"。\n\n"
        f"{fragments}"
        f"问题：{question}\n\n"
        "给出答案，末尾列出引用的来源章节。"
    )


def ask_llm(prompt: str) -> str:
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def print_answer(question: str, answer: str, hits: list[dict]) -> None:
    sources = list(dict.fromkeys(h["section_path"] for h in hits))
    sep = "━" * 50
    print(f"\n{sep}")
    print(f"问题：{question}\n")
    print(f"答案：\n{answer}\n")
    print("来源章节：")
    for s in sources:
        print(f"  · {s}")
    print(sep)


def main(file_path: str) -> None:
    try:
        index, chunk_map, conn = load_resources()
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print(f"已加载索引（{index.ntotal} 个 chunk），输入问题开始检索，输入 q 退出\n")

    while True:
        question = input("请输入问题：").strip()
        if question.lower() == "q":
            break
        if not question:
            continue
        try:
            vec = embed_query(question)
            hits = recall(index, chunk_map, conn, vec)
            prompt = build_prompt(question, hits)
            answer = ask_llm(prompt)
            print_answer(question, answer, hits)
        except Exception as e:
            print(f"[错误] {e}\n")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：uv run query.py <招标文件.md>")
        sys.exit(1)
    main(sys.argv[1])
