# processor/import_processor/nodes/node_import_milvus.py

from processor.import_processor.base import BaseNode
from processor.import_processor.state import ImportGraphState


class NodeImportMilvus(BaseNode):
    """
    导入向量库节点：数据持久化
    """

    name = "node_import_milvus"

    def process(self, state: ImportGraphState):
        # 将数据存入 milvus里面的 逻辑

        return state