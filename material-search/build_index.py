import os
import json
import time
import numpy as np
import pandas as pd
import faiss
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ─── 配置 ────────────────────────────────────────────────
EXCEL_PATH = "客户信息与物料对应关系.xlsx"
ROW_START  = 0       # 从第几行开始（0 = 第一行数据）
ROW_END    = 500     # 到第几行结束（验证阶段先跑 500 条）
BATCH_SIZE = 10      # text-embedding-v4 单次最多 10 条
DIM        = 1024    # 向量维度

INDEX_FILE = "material.index"   # FAISS 索引文件
META_FILE  = "material_meta.json"  # 物料信息映射表

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# ─── 读取 Excel ───────────────────────────────────────────
def load_data(path, start, end):
    df = pd.read_excel(path, dtype=str).fillna("")
    df = df.iloc[start:end].reset_index(drop=True)
    print(f"读取 {len(df)} 条记录（行 {start} ~ {end}）")
    return df

# ─── 拼接文本 ─────────────────────────────────────────────
def build_text(row):
    name = row.get("物料名称", "").strip()
    desc = row.get("绑定的描述", "").strip()
    if name and desc:
        return f"{name} {desc}"
    return name or desc

# ─── 批量调用 API 获取向量 ────────────────────────────────
def get_embeddings(texts: list[str]) -> list[list[float]]:
    result = []
    total  = len(texts)
    for i in range(0, total, BATCH_SIZE):
        batch = texts[i: i + BATCH_SIZE]
        try:
            resp = client.embeddings.create(
                model="text-embedding-v4",
                input=batch,
                dimensions=DIM,
                encoding_format="float",
            )
            batch_vecs = [item.embedding for item in resp.data]
            result.extend(batch_vecs)
            print(f"  向量化进度：{min(i + BATCH_SIZE, total)}/{total}")
        except Exception as e:
            print(f"  第 {i} 批次失败：{e}，等待 3s 重试...")
            time.sleep(3)
            resp = client.embeddings.create(
                model="text-embedding-v4",
                input=batch,
                dimensions=DIM,
                encoding_format="float",
            )
            result.extend([item.embedding for item in resp.data])
        time.sleep(0.1)  # 避免触发限速
    return result

# ─── 保存 FAISS 索引 ──────────────────────────────────────
def save_index(vectors: list[list[float]], index_path: str):
    mat = np.array(vectors, dtype="float32")
    faiss.normalize_L2(mat)  # 归一化后用内积 = 余弦相似度
    index = faiss.IndexFlatIP(DIM)
    index.add(mat)
    faiss.write_index(index, index_path)
    print(f"FAISS 索引已保存：{index_path}（共 {index.ntotal} 条）")

# ─── 保存物料映射表 ───────────────────────────────────────
def save_meta(df: pd.DataFrame, meta_path: str):
    records = []
    for _, row in df.iterrows():
        records.append({
            "物料编码": row.get("物料编码", ""),
            "物料名称": row.get("物料名称", ""),
            "绑定的描述": row.get("绑定的描述", ""),
            "客户名称": row.get("客户名称", ""),
            "产品名称": row.get("产品名称", ""),
        })
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"物料映射表已保存：{meta_path}（共 {len(records)} 条）")

# ─── 主流程 ───────────────────────────────────────────────
def main():
    df      = load_data(EXCEL_PATH, ROW_START, ROW_END)
    texts   = [build_text(row) for _, row in df.iterrows()]

    print(f"\n开始向量化，共 {len(texts)} 条...")
    vectors = get_embeddings(texts)

    print("\n保存索引和映射表...")
    save_index(vectors, INDEX_FILE)
    save_meta(df, META_FILE)

    print("\n✅ 入库完成")

if __name__ == "__main__":
    main()
