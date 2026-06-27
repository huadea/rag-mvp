import os
import json
import numpy as np
import faiss
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ─── 配置 ────────────────────────────────────────────────
INDEX_FILE   = "material.index"
META_FILE    = "material_meta.json"
DIM          = 1024
RECALL_K     = 20   # FAISS 粗排召回数量
TOP_K        = 5    # 精排后最终返回数量

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

rerank_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
)

# ─── 加载索引和映射表 ─────────────────────────────────────
def load_index(index_path, meta_path):
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"索引文件不存在: {index_path}，请先运行 build_index.py")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"元数据文件不存在: {meta_path}，请先运行 build_index.py")
    index = faiss.read_index(index_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"已加载索引（{index.ntotal} 条）和映射表（{len(meta)} 条）\n")
    return index, meta

# ─── 查询文本转向量 ───────────────────────────────────────
def get_query_vector(text: str) -> np.ndarray:
    resp = client.embeddings.create(
        model="text-embedding-v4",
        input=[text],
        dimensions=DIM,
        encoding_format="float",
    )
    vec = np.array([resp.data[0].embedding], dtype="float32")
    faiss.normalize_L2(vec)
    return vec

# ─── 构建精排输入文本 ─────────────────────────────────────
def build_document_text(item: dict) -> str:
    name = item.get("物料名称", "").strip()
    desc = item.get("绑定的描述", "").strip()
    if name and desc:
        return f"{name} {desc}"
    return name or desc

# ─── FAISS 粗排召回 ───────────────────────────────────────
def recall(index, meta, query_vec, recall_k=RECALL_K):
    k = min(recall_k, index.ntotal)
    scores, indices = index.search(query_vec, k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(meta):
            continue
        item = meta[idx].copy()
        item["_score"] = float(score)
        results.append(item)
    return results

# ─── qwen3-rerank 精排 ────────────────────────────────────
def rerank(query: str, documents: list[str], top_n: int = TOP_K) -> list[dict]:
    response = rerank_client.post(
        "/reranks",
        body={
            "model": "qwen3-rerank",
            "query": query,
            "documents": documents,
            "top_n": top_n,
        },
        cast_to=object,
    )
    results = response.get("results", response) if isinstance(response, dict) else response.results
    return [
        {"index": r["index"], "score": r["relevance_score"]}
        if isinstance(r, dict) else {"index": r.index, "score": r.relevance_score}
        for r in results
    ]

# ─── 打印结果 ─────────────────────────────────────────────
def print_results(query, results):
    print(f"查询：{query}")
    print("─" * 80)
    for r in results:
        print(f"Top{r['排名']}  相关性得分：{r['相关性得分']}")
        print(f"  物料编码：{r['物料编码']}")
        print(f"  物料名称：{r['物料名称']}")
        desc = r.get("绑定的描述", "")
        print(f"  绑定描述：{desc[:80]}{'...' if len(desc) > 80 else ''}")
        print(f"  客户名称：{r.get('客户名称', '')}")
        print(f"  产品名称：{r.get('产品名称', '')}")
        print()

# ─── 主流程（交互式循环）────────────────────────────────────
def main():
    try:
        index, meta = load_index(INDEX_FILE, META_FILE)
    except FileNotFoundError as e:
        print(f"错误：{e}")
        return

    print("输入新物料描述进行查询，输入 q 退出\n")
    while True:
        query = input("请输入物料描述：").strip()
        if query.lower() == "q":
            break
        if not query:
            continue

        try:
            vec = get_query_vector(query)
            candidates = recall(index, meta, vec, RECALL_K)

            doc_texts = [build_document_text(c) for c in candidates]
            try:
                ranked = rerank(query, doc_texts, TOP_K)
            except Exception as e:
                print(f"[精排失败，回退到粗排结果：{e}]")
                ranked = [
                    {"index": i, "score": c["_score"]}
                    for i, c in enumerate(candidates[:TOP_K])
                ]

            results = []
            for rank, r in enumerate(ranked, start=1):
                item = candidates[r["index"]].copy()
                results.append({
                    "排名": rank,
                    "相关性得分": round(r["score"], 4),
                    "物料编码": item.get("物料编码", ""),
                    "物料名称": item.get("物料名称", ""),
                    "绑定的描述": item.get("绑定的描述", ""),
                    "客户名称": item.get("客户名称", ""),
                    "产品名称": item.get("产品名称", ""),
                })

            print()
            print_results(query, results)
        except Exception as e:
            print(f"查询失败：{e}\n")

if __name__ == "__main__":
    main()
