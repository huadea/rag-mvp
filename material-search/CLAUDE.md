# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Material search tool that converts material data from an Excel file into vector embeddings and builds a FAISS similarity search index. Uses Alibaba DashScope's text-embedding-v4 model via the OpenAI-compatible API.

## Commands

- **Run the index builder**: `uv run python build_index.py`
- **Run main**: `uv run python main.py`
- **Install dependencies**: `uv sync`

## Architecture

**`build_index.py`** is the core script with this pipeline:
1. Reads `客户信息与物料对应关系.xlsx` (row range configurable via `ROW_START`/`ROW_END` constants)
2. Concatenates `物料名称` + `绑定的描述` columns as embedding input text
3. Calls DashScope embeddings API in batches of 10 (`BATCH_SIZE`)
4. Builds a FAISS `IndexFlatIP` (inner product = cosine similarity after L2 normalization) with 1024-dim vectors
5. Outputs `material.index` (FAISS index) and `material_meta.json` (metadata mapping with 物料编码/物料名称/描述/客户名称/产品名称)

**`main.py`** is a placeholder entry point.

## Environment

- **Python**: 3.13 (managed via uv)
- **Required env var**: `DASHSCOPE_API_KEY` — DashScope API key for embedding generation
- **Package manager**: uv (`pyproject.toml` + `uv.lock`)
