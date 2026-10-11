# processor/query_processor/nodes/node_web_search_mcp.py
import asyncio
import json

from agents.mcp import MCPServerStreamableHttp

from config.bailian_mcp_config import mcp_config
from processor.query_processor.base import NodeBase
from processor.query_processor.state import QueryGraphState
from tool.logger import logger
from utils.json_format_utils import serialize_json
from utils.task_utils import add_done_task


class NodeWebSearchMcp(NodeBase):
    """
    节点功能，调用外部搜索引擎补充信息
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_web_search_mcp"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        query = state.get("rewritten_query","")
        docs = []
        # 如果没有查询内容，直接返回
        if query:
            # MCP 端点偶发握手超时/网络抖动时，联网搜索是「锦上添花」而非主链路，
            # 失败时记录告警并降级跳过，不阻断后续 RRF/rerank/answer_output。
            try:
                result = asyncio.run(self._mcp_call(query))
            except Exception as e:
                logger.warning(
                    f"MCP 联网搜索失败，已降级跳过（不影响主流程）: "
                    f"{type(e).__name__}: {e}"
                )
                result = None
            if result:
                pages = json.loads(result.content[0].text).get("pages") or []
                # 统一输出结构化结果，供后续 rerank/ 引用使用
                # 每条：{title,url,snippet}

                for item in pages:
                    snippet = (item.get("snippet") or "").strip()
                    url = (item.get("url") or "").strip()
                    title = (item.get("title") or "").strip()
                    if not snippet:
                        continue

                    docs.append({"title": title, "url": url, "snippet": snippet})

                logger.info(f"MCP 搜索结果：{docs}")

        # 记录节点完成状态，供前端轮询进度展示
        add_done_task(state.get("session_id"), self.name, state.get("is_stream"))

        if docs:
            return {"web_search_docs": docs}
        return {}

    async def _mcp_call(self, query):
        search_mcp = MCPServerStreamableHttp(
            name="search_mcp",  # 要使用的插件名称（可自定义）比如我的搜索服务
            params={
                "url":mcp_config.mcp_base_url,
                "headers":{"Authorization":f"Bearer {mcp_config.api_key}"},
                "timeout":10,
            },
            cache_tools_list=True,  # 第1次请求，后续缓存不重复请求（服务器上有哪些工具）
            max_retry_attempts=3,   # 网络异常时重试次数
        )

        try:
            await search_mcp.connect()
            result = await search_mcp.call_tool(
                tool_name="bailian_web_search",     # 使用的插件名称（不能错）
                arguments={"query": query,"count":5},
            )
            return result
        finally:
            await search_mcp.cleanup()


if __name__ == "__main__":

    init_state = {
        "rewritten_query": "H3CLA2608室内无线网关如何接通"
    }

    # 执行节点的业务调用
    node_web_search_mcp = NodeWebSearchMcp()
    result = node_web_search_mcp(init_state)
    logger.info(serialize_json(result, indent=4))