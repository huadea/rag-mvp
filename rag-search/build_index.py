"""
入库脚本。

用法：
    uv run build_index.py <招标文件.md>

输出：
    rag.db           SQLite，存 chunk 元数据和原文
    chunks.index     FAISS 向量索引
    chunks_map.json  FAISS 位置 → chunk_id 映射
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

import chunker

load_dotenv()

DB_PATH    = "rag.db"
INDEX_PATH = "chunks.index"
MAP_PATH   = "chunks_map.json"

DIM        = 1024
BATCH_SIZE = 10

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id     TEXT PRIMARY KEY,
            document_id  TEXT,
            section_path TEXT,
            chunk_text   TEXT,
            source_text  TEXT,
            chunk_type   TEXT,
            package_no   TEXT,
            created_at   TEXT
        )
    """)
    conn.commit()


def clear_document(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    conn.commit()


def insert_chunks(conn: sqlite3.Connection, chunks: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO chunks
           (chunk_id, document_id, section_path, chunk_text, source_text, chunk_type, package_no, created_at)
           VALUES (:chunk_id, :document_id, :section_path, :chunk_text, :source_text, :chunk_type, :package_no, :created_at)
        """,
        chunks,
    )
    conn.commit()


def get_embeddings(texts: list[str]) -> list[list[float]]:
    result = []
    total = len(texts)
    for i in range(0, total, BATCH_SIZE):
        batch = texts[i: i + BATCH_SIZE]
        try:
            resp = client.embeddings.create(
                model="text-embedding-v4",
                input=batch,
                dimensions=DIM,
                encoding_format="float",
            )
            result.extend(item.embedding for item in resp.data)
            print(f"  向量化进度：{min(i + BATCH_SIZE, total)}/{total}")
        except Exception as e:
            print(f"  第 {i} 批次失败：{e}，3s 后重试...")
            time.sleep(3)
            resp = client.embeddings.create(
                model="text-embedding-v4",
                input=batch,
                dimensions=DIM,
                encoding_format="float",
            )
            result.extend(item.embedding for item in resp.data)
        time.sleep(0.1)
    return result


def build_faiss(vectors: list[list[float]]) -> faiss.IndexFlatIP:
    mat = np.array(vectors, dtype="float32")
    faiss.normalize_L2(mat)
    index = faiss.IndexFlatIP(DIM)
    index.add(mat)
    return index


def main(file_path: str) -> None:
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"[错误] 文件不存在：{path}")
        sys.exit(1)
    if path.suffix.lower() != ".md":
        print(f"[错误] 仅支持 .md 文件")
        sys.exit(1)

    print(f"[1/4] 切块：{path.name}")
    chunks = chunker.chunk_document(str(path))
    print(f"      共 {len(chunks)} 个 chunk")

    print("[2/4] 写入 SQLite...")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    clear_document(conn, chunks[0]["document_id"])
    insert_chunks(conn, chunks)
    conn.close()
    print(f"      已写入 {DB_PATH}")

    print("[3/4] 向量化...")
    texts = [c["chunk_text"] for c in chunks]
    vectors = get_embeddings(texts)

    print("[4/4] 构建 FAISS 索引...")
    index = build_faiss(vectors)
    faiss.write_index(index, INDEX_PATH)
    chunk_ids = [c["chunk_id"] for c in chunks]
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(chunk_ids, f, ensure_ascii=False)
    print(f"      已保存 {INDEX_PATH} 和 {MAP_PATH}")

    print(f"\n完成！共 {len(chunks)} 个 chunk 入库。")
    print(f"查询：uv run query.py \"{file_path}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：uv run build_index.py <招标文件.md>")
        sys.exit(1)
    main(sys.argv[1])
