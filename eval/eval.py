"""
基于 Ragas 的知识库 RAG 批量评估程序。
流程：读取 eval/qa.csv 测试集 -> 调用 RAG 流程(query_app.invoke)生成答案 ->
     从 state["reranked_docs"] 提取上下文证据 -> 用 5 项 Ragas 指标打分 ->
     输出 eval/qa_result.csv（utf-8 BOM，9 列）。
注意：本文件必须能从任意工作目录运行，因此在导入项目模块前先补齐 sys.path。
"""
from __future__ import annotations
import os  # 操作系统环境变量、文件系统操作
import sys  # 系统路径、模块劫持，用于解决导入路径问题
from datetime import datetime  # 计算评估耗时
from pathlib import Path  # 面向对象路径处理，跨平台兼容
from unittest.mock import MagicMock  # mock 不存在的模块，防止 ragas 导入崩溃
from uuid import uuid4  # 生成唯一 session_id / message_id，隔离评估会话

# ===================== 路径与环境准备（必须早于项目模块导入） =====================
# 获取当前脚本所在 eval 目录的绝对路径
EVAL_DIR = Path(__file__).resolve().parent
# 项目根目录：eval 的上一级目录
PROJECT_ROOT = EVAL_DIR.parent

# 将项目根目录插入 sys.path 头部，支持 python eval/eval.py 任意目录直接运行
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# mock langchain_community vertexai 模块，规避 ragas 导入时加载已移除模块导致崩溃
if "langchain_community.chat_models.vertexai" not in sys.modules:
    sys.modules["langchain_community.chat_models.vertexai"] = MagicMock()

# 设置环境变量，关闭 MongoDB 会话历史，离线评估不需要数据库依赖
os.environ.setdefault("MONGO_HISTORY_ENABLED", "false")

from typing import Any  # 通用任意类型注解
import pandas as pd  # csv读写、数据表格处理
from datasets import Dataset  # HuggingFace Dataset，ragas 要求的输入数据结构
from langchain_core.embeddings import Embeddings  # LangChain Embedding 抽象基类，做适配器
from ragas import evaluate  # ragas 核心评估函数

# ragas0.4.x 规避弃用警告：直接从内部实现模块导入指标实例，evaluate仅接受旧式Metric实例
from ragas.metrics._answer_correctness import answer_correctness  # 答案正确性指标
from ragas.metrics._answer_relevance import answer_relevancy      # 答案相关性指标
from ragas.metrics._context_precision import context_precision    # 上下文精确率指标
from ragas.metrics._context_recall import context_recall          # 上下文召回率指标
from ragas.metrics._faithfulness import faithfulness              # 事实忠实度指标
from ragas.run_config import RunConfig  # ragas运行配置：并发、超时、重试参数

from utils.embedding_utils import generate_embeddings, get_bge_m3_ef  # 项目内部embedding工具
from utils.llm_utils import get_llm_client                            # 项目内部llm客户端获取工具

# 必须在 MONGO_HISTORY_ENABLED 设置完成后导入，该模块读取此环境变量
from processor.query_processor.main_graph import query_app  # RAG应用入口图对象
from processor.query_processor.state import create_default_state  # 构造RAG流程初始state

# 测试集输入文件路径
INPUT_FILE = EVAL_DIR / "qa.csv"
# 评估结果输出文件路径
OUTPUT_FILE = EVAL_DIR / "qa_result.csv"

# 输出csv固定9列以及输出顺序
OUTPUT_COLUMNS = [
    "question",
    "context",
    "answer",
    "ground_truth",
    "Faithfulness",
    "Answer Relevancy",
    "Context Precision",
    "Context Recall",
    "Answer Correctness",
]

# ragas返回的指标列名映射到输出csv展示列名
METRIC_COLUMN_MAP = {
    "faithfulness": "Faithfulness",
    "answer_relevancy": "Answer Relevancy",
    "context_precision": "Context Precision",
    "context_recall": "Context Recall",
    "answer_correctness": "Answer Correctness",
}


class BgeM3LangChainEmbeddings(Embeddings):
    """将项目的 BGE-M3 模型适配成 Ragas 可使用的 LangChain Embeddings 接口。"""
    def __init__(self, embedding_model: Any) -> None:
        """
        保存由项目工具创建的 BGE-M3 模型实例。
        :param embedding_model: utils.embedding_utils.get_bge_m3_ef() 返回的对象
        """
        self.embedding_model = embedding_model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        批量生成文档的稠密向量。
        :param texts: 待向量化的文本列表
        :return: 稠密向量列表
        """
        if not texts:  # 空输入直接返回空列表
            return []
        result = generate_embeddings(texts)  # 调用项目工具批量向量化
        if not result:
            raise RuntimeError("BGE-M3 文档向量生成失败")
        return result["dense"]  # 返回稠密向量部分，ragas只用dense向量

    def embed_query(self, text: str) -> list[float]:
        """
        生成单条查询的稠密向量。
        :param text: 查询文本
        :return: 稠密向量
        """
        return self.embed_documents([text])[0]  # 复用批量接口取第一条结果


def _extract_contexts(reranked_docs: list[Any]) -> list[str]:
    """
    从 state["reranked_docs"] 中提取非空的正文内容，作为 Ragas 的上下文证据。
    兼容 dict（含 content 字段）与 LangChain Document（含 page_content 属性）。
    :param reranked_docs: 重排后的文档列表
    :return: 上下文文本列表
    """
    contexts: list[str] = []
    for doc in reranked_docs or []:
        # 判断文档是字典结构还是LangChain Document对象
        if isinstance(doc, dict):
            content = str(doc.get("content") or "").strip()
        else:
            content = str(getattr(doc, "page_content", "") or "").strip()
        if content:  # 过滤掉空内容
            contexts.append(content)
    return contexts


def step_1_load_test_set(input_file: Path = INPUT_FILE) -> pd.DataFrame:
    """
    步骤一：读取并校验评估测试集（question、ground_truth 两列，utf-8 BOM）。
    :param input_file: 测试集 CSV 路径
    :return: 仅含 question、ground_truth 的 DataFrame
    """
    print(f"\n[Step 1] 正在加载评估测试集: {input_file}")
    if not input_file.is_file():  # 判断文件是否存在
        raise FileNotFoundError(f"评估测试集不存在: {input_file}")
    # utf‑8‑sig 读取带BOM的csv，Windows Excel打开不乱码
    test_df = pd.read_csv(input_file, encoding="utf-8-sig")
    # 校验必须存在的列
    missing_columns = {"question", "ground_truth"}.difference(test_df.columns)
    if missing_columns:
        raise ValueError(f"评估测试集缺少必要列: {', '.join(sorted(missing_columns))}")
    if test_df.empty:
        raise ValueError("评估测试集不能为空")
    # 只保留需要的两列，生成副本避免修改原始数据
    test_df = test_df.loc[:, ["question", "ground_truth"]].copy()
    # 检查是否存在NaN空值
    if test_df.isnull().any().any():
        raise ValueError("question 和 ground_truth 列不能包含空值")
    # 转为字符串并且去除首尾空白字符
    test_df["question"] = test_df["question"].astype(str).str.strip()
    test_df["ground_truth"] = test_df["ground_truth"].astype(str).str.strip()
    # 检查是否有空字符串
    if (test_df == "").any().any():
        raise ValueError("question 和 ground_truth 列不能包含空字符串")
    print(f"[Step 1] 成功加载测试集，共 {len(test_df)} 条数据。")
    return test_df


def step_2_run_rag(test_df: pd.DataFrame) -> pd.DataFrame:
    """
    步骤二：逐条调用 RAG 流程入口 query_app.invoke，收集答案与重排后的上下文证据。
    :param test_df: 含 question、ground_truth 的测试集
    :return: 含 question、contexts、answer、ground_truth 的 DataFrame
    """
    print("\n[Step 2] 开始执行 RAG 检索与生成流程...")
    rag_rows: list[dict[str, Any]] = []  # 存储每条RAG运行结果
    session_id = f"ragas-eval-{uuid4().hex}"  # 本次评估统一会话ID
    # 遍历测试集，row_number从1开始展示进度
    for row_number, row in enumerate(test_df.itertuples(index=False), start=1):
        question = row.question
        print(f"  -> [{row_number}/{len(test_df)}] 正在执行 RAG: {question[:30]}...")
        # 构建RAG初始状态对象
        state = create_default_state(
            original_query=question,
            session_id=session_id,
            message_id=f"ragas-eval-{uuid4().hex}",
            is_stream=False,  # 评估使用非流式输出
        )
        final_state = query_app.invoke(state)  # 调用RAG图执行完整流程
        if not isinstance(final_state, dict):
            raise RuntimeError(f"RAG 未返回有效 state，问题: {question}")
        answer = str(final_state.get("answer") or "").strip()  # 获取生成答案
        contexts = _extract_contexts(final_state.get("reranked_docs") or [])  # 提取检索上下文
        if not contexts:
            print(f"     警告：该问题未召回到任何上下文，相关指标可能偏低。")
        # 将单条结果存入列表
        rag_rows.append(
            {
                "question": question,
                "contexts": contexts,
                "answer": answer,
                "ground_truth": row.ground_truth,
            }
        )
    print(f"[Step 2] RAG 流程执行完毕，成功生成 {len(rag_rows)} 条结果。")
    return pd.DataFrame(rag_rows)


def step_3_get_evaluation_models() -> tuple[Any, Embeddings]:
    """
    步骤三：获取 Ragas 评估用的 LLM 与 Embedding 模型。
    LLM 来自 utils.llm_utils.get_llm_client，Embedding 来自 utils.embedding_utils.get_bge_m3_ef。
    :return: (LLM 客户端, 适配后的 Embeddings 对象)
    """
    print("\n[Step 3] 正在初始化评估模型 (LLM & BGE-M3 Embeddings)...")
    # 开启json_mode，ragas评估需要大模型输出结构化json，降低解析报错概率
    llm = get_llm_client(json_mode=True)
    if llm is None:
        raise RuntimeError("无法通过 get_llm_client 获取评估 LLM")
    embedding_model = get_bge_m3_ef()
    if embedding_model is None:
        raise RuntimeError("无法通过 get_bge_m3_ef 获取嵌入模型")
    print("[Step 3] 评估模型初始化成功。")
    return llm, BgeM3LangChainEmbeddings(embedding_model)


def step_4_evaluate_with_ragas(
        rag_df: pd.DataFrame, llm: Any, embeddings: Embeddings
) -> pd.DataFrame:
    """
    步骤四：使用 5 项 Ragas 指标进行评估，并容忍单个模型结果解析失败。
    :param rag_df: 含 question、contexts、answer、ground_truth 的数据
    :param llm: 评估用 LLM
    :param embeddings: 评估用 Embeddings
    :return: 包含 9 列输出结构的 DataFrame
    """
    print("\n[Step 4] 正在使用 Ragas 进行多维度评估...")
    # pandas dataframe转为huggingface Dataset，这是ragas要求输入格式
    evaluation_dataset = Dataset.from_dict(
        {
            "question": rag_df["question"].tolist(),
            "contexts": rag_df["contexts"].tolist(),
            "answer": rag_df["answer"].tolist(),
            "ground_truth": rag_df["ground_truth"].tolist(),
        }
    )
    start_time = datetime.now()  # 记录评估开始时间
    evaluation_result = evaluate(
        dataset=evaluation_dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
            answer_correctness,
        ],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,  # 单条样本失败置NaN，不中断整个评估
        run_config=RunConfig(
            timeout=180,       # 单条请求超时秒数
            max_retries=5,     # LLM调用最大重试次数
            max_wait=10,       # 退避最大等待时间
            max_workers=2,     # 降低并发数，防止大模型限流、报错
        ),
    )
    cost_seconds = (datetime.now() - start_time).total_seconds()  # 计算总耗时
    print(f"[Step 4] Ragas 评估完成！共耗时: {cost_seconds:.2f} 秒。")
    score_df = evaluation_result.to_pandas()  # ragas结果转pandas
    result_df = rag_df.copy()
    # list上下文数组拼接成换行分隔字符串，用于输出csv查看
    result_df["context"] = result_df["contexts"].apply(lambda items: "\n\n".join(items))
    # 将ragas内部列名映射为输出csv列名
    for ragas_column, output_column in METRIC_COLUMN_MAP.items():
        if ragas_column not in score_df.columns:
            raise RuntimeError(f"Ragas 评估结果缺少指标列: {ragas_column}")
        result_df[output_column] = score_df[ragas_column].to_numpy()
    # 只保留规定输出9列，固定顺序
    result_df = result_df.loc[:, OUTPUT_COLUMNS]
    # 统计NaN分数数量，即解析失败的指标
    missing_score_count = int(
        result_df[list(METRIC_COLUMN_MAP.values())].isna().sum().sum()
    )
    if missing_score_count:
        print(
            f"警告：有 {missing_score_count} 个指标因模型输出解析失败而记为 NaN，"
            "其余评估结果仍会正常保存。"
        )
    return result_df


def step_5_save_result(
        result_df: pd.DataFrame, output_file: Path = OUTPUT_FILE
) -> None:
    """
    步骤五：按 9 列顺序，以 UTF-8 BOM 编码保存评估结果。
    :param result_df: 评估结果 DataFrame
    :param output_file: 输出 CSV 路径
    """
    print(f"\n[Step 5] 正在保存评估结果至: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)  # 目录不存在自动创建
    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")  # utf‑8‑sig带BOM兼容Excel
    print("[Step 5] 文件保存成功！")


def step_6_print_summary(result_df: pd.DataFrame) -> None:
    """
    步骤六：在控制台打印各指标的均分，便于快速判断整体效果。
    :param result_df: 评估结果 DataFrame
    """
    print("\n[Step 6] 各指标平均分：")
    # OUTPUT_COLUMNS[4:] 取出5个指标列，计算平均值，coerce把非数字转为NaN
    for column in OUTPUT_COLUMNS[4:]:
        print(f"  - {column}: {pd.to_numeric(result_df[column], errors='coerce').mean():.4f}")


def main() -> None:
    """按读取测试集、执行 RAG、初始化模型、评估、保存、汇总的顺序运行完整流程。"""
    print("=" * 60)
    print("开始执行 RAG 知识库批量评估流程...")
    print("=" * 60)
    test_df = step_1_load_test_set()          # 1.加载测试集
    rag_df = step_2_run_rag(test_df)          # 2.批量跑RAG获取答案与上下文
    llm, embeddings = step_3_get_evaluation_models()  # 3.初始化评估LLM、Embedding
    result_df = step_4_evaluate_with_ragas(rag_df, llm, embeddings)  # 4.Ragas打分
    step_5_save_result(result_df)             # 5.保存csv结果文件
    step_6_print_summary(result_df)           # 6.控制台输出指标汇总
    print("\n" + "=" * 60)
    print(f"评估全部完成！结果已保存至: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()  # 脚本直接运行时启动评估主函数
