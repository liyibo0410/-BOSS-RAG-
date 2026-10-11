# processor/query_processor/state.py

from typing import TypedDict, List

class QueryGraphState(TypedDict):
    """
    查询流程图状态
    包含整个查询流程中传递的所有数据。
    """

    session_id: str  # 会话ID
    message_id: str  # 消息ID

    original_query: str  # 用户原始问题

    # 检索过程中的中间数据
    embedding_chunks: list  # 普通向量检索回来的切片
    hyde_embedding_chunks: list  # 已向量化的假设性问题切片
    web_search_docs: list  # 网络搜索回来的文档

    # 排序过程中的数据
    rrf_chunks: list  # RRF 融合排序后的切片
    reranked_docs: list  # 重排序后的最终 Top-K 文档

    # 生成过程中的数据
    prompt: str  # 组装好的 Prompt
    answer: str  # 最终生成的答案

    # 辅助信息
    item_names: List[str]  # 提取出的商品名称
    rewritten_query: str  # 改写后的问题   理解用户的意图
    history: list  # 历史对话记录
    is_stream: bool  # 是否流式输出


def create_default_state(
        original_query: str = "",
        session_id: str = "",
        message_id: str = "",
        is_stream: bool = False,
        task_id: str = "",
) -> QueryGraphState:
    """
    构造查询流程的初始状态。

    所有字段都给出默认值，避免节点读取尚未写入的键时抛出 KeyError。
    :param original_query: 用户原始问题
    :param session_id: 会话ID（查询流程中同时作为任务ID使用）
    :param message_id: 消息ID
    :param is_stream: 是否流式输出
    :param task_id: 任务ID，仅保持调用兼容；查询流程统一使用 session_id 跟踪任务
    :return: 初始化后的 QueryGraphState
    """
    return QueryGraphState(
        session_id=session_id,
        message_id=message_id,
        original_query=original_query,
        embedding_chunks=[],
        hyde_embedding_chunks=[],
        web_search_docs=[],
        rrf_chunks=[],
        reranked_docs=[],
        prompt="",
        answer="",
        item_names=[],
        rewritten_query="",
        history=[],
        is_stream=is_stream,
    )