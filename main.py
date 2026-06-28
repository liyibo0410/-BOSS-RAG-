import sys
import json
from pathlib import Path
from processor.import_processor.base import setup_logging
from processor.import_processor.main_graph import KBImportWorkflow
from processor.import_processor.state import get_default_state
import logging

root = Path(__file__).parent
sys.path.insert(0, str(root))

if __name__ == "__main__":
    setup_logging()

    test_file_path = r"D:\output\联想海豚用户手册\联想海豚用户手册.md"
    if not Path(test_file_path).exists():
        logging.warning(f"测试文件不存在: {test_file_path}，将使用空状态运行工作流")
        test_file_path = ""

    init_state = get_default_state()
    init_state["import_file_path"] = test_file_path

    workflow = KBImportWorkflow()
    result = workflow.run(init_state)

    logging.info(json.dumps(result, ensure_ascii=False, indent=4))
