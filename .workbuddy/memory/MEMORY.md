# 项目长期记忆：BOSS 智库（knowledge_base）

## 项目定位
企业级 RAG 知识库。FastAPI + LangGraph + Milvus(混合检索) + MongoDB(对话历史)
+ MinIO(文件) + BGE-M3(稠密+稀疏向量) + DashScope Qwen。

- 导入服务：`web/api/import_service.py`，端口 **8000**，页面 `/import.html`
- 查询服务：`web/api/query_service.py`，端口 **8001**，页面 `/chat.html`
- 启动：`uvicorn web.api.import_service:app --port 8000`
         `uvicorn web.api.query_service:app --port 8001`

## 原始基准包（重要）
`D:\个人文件\AI大模型学习资料\13-企业级智能知识库系统项目\knowledge_base.7z`
是教程最终版（day13）完整项目。排查"哪里被改坏了"时，解压它做全量 diff 是最有效手段。
注意当前项目是基准的**演进版**，不要整体回滚覆盖。

## 本机环境事实
- **只有 `docker-compose` v5.4.0（v1 独立命令），没有 `docker compose` v2 插件**。
  任何脚本/文档里写 `docker compose` 都会失败，需写成 `docker-compose` 或做探测。
- `.venv` 由 uv 管理，**内部没有 pip**。装包用 `uv sync` / `uv add`，
  跑脚本用 `.venv/Scripts/python.exe`。
- `python - <<EOF` stdin 模式下 `load_dotenv()` 会 AssertionError，需 `load_dotenv('.env')`。
- Python 3.11（`.python-version` / `pyproject.toml` 均为 `==3.11.*`）。

## 依赖红线
`pyproject.toml` 中**禁止**添加 `config` / `utils` / `processor` / `knowledge` 依赖：
它们是 PyPI 上与本地包同名的无关第三方包，会抢 import 并污染 uv.lock。
本地包靠项目根目录在 sys.path 直接导入，无需声明。

## 中间件运维
- 一键启动：双击 `start-middleware.bat`（已自适应 compose v1/v2）
- 自检：`.venv/Scripts/python.exe check_env.py`
- Milvus 若报 `rocksmq ... CURRENT file corrupted`：
  重命名备份 `volumes/milvus/rdb_data` **和** `volumes/milvus/rdb_data_meta_kv`
  （两个都要，只移一个仍会报同样错），Milvus 重启后自动重建。
  MinIO 桶 `knowledge-base` 会由 `utils/minio_utils.py` 首次调用时自动创建。

## API 平台分工（易踩坑）
当前全家桶走**阿里云百炼（DashScope）**，同一个 `sk-ws-` 百炼 key 可用于三处：

| 用途 | 配置项 | 当前值 |
|---|---|---|
| LLM 对话 | `OPENAI_API_KEY` + `OPENAI_API_BASE` | 百炼 key + `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 重排序 rerank | `MCP_API_KEY`（`reranker_http_utils.py` 硬编码 dashscope SDK） | 百炼 key，model=qwen3-rerank |
| MCP 联网搜索 | `MCP_API_KEY` + `MCP_DASHSCOPE_BASE_URL` | 百炼 key + `https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp` |
| 视觉模型 | `VL_MODEL`=qwen3-vl-flash | 复用 LLM key |
| 向量嵌入 | 本地 BGE-M3（路径 `BGE_M3_PATH`，不花钱） | — |

- 实测：百炼的 `sk-ws-` WebSearch 专用 key **也能用于** LLM 兼容模式（qwen-flash/plus/turbo 均过）。
- **MCP 联网搜索端点大坑**：`node_web_search_mcp.py` 用 `MCPServerStreamableHttp`（Streamable HTTP 传输），
  所以 `MCP_DASHSCOPE_BASE_URL` **必须是 `.../mcps/WebSearch/mcp`**。填 `.../mcps/WebSearch/sse`（旧版 SSE 协议）会让握手卡在
  `session.initialize()` 超时；填 MaaS 兼容模式地址 `...maas.aliyuncs.com/compatible-mode/v1` 会直接 `Session terminated`。
  `.env.example` 原写的 `/sse` 已过期，已改为 `/mcp`（2026-09-07 修）。
- **若临时把 LLM 切到硅基流动**（`OPENAI_API_BASE=https://api.siliconflow.cn/v1`），
  `MCP_API_KEY` 必须仍填阿里云 key（rerank/MCP 硬编码用阿里云），两个 key 不能复用同个平台
  —— 否则 rerank 报 **401 Invalid API-key**，硅基流动欠费则 LLM 报 **402**。
- `.env` 中 `BGE_RERANKER_LARGE` / `MD_ROOT_DIR` / `MODELSCOPE_CACHE` / `HF_HOME`
  均为**无人引用的遗留配置**，路径不存在也不影响运行，不必修。
