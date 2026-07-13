import json
import os

from app.import_process.agent.main_graph import kb_import_app
from app.import_process.agent.state import create_default_state
from app.utils.path_util import PROJECT_ROOT
from app.core.logger import logger

logger.info("===== 开始测试 =====")

test_file_name = "万用表RS-12的使用.md"
test_file_path = os.path.join(PROJECT_ROOT, test_file_name)
logger.info(f"测试文件路径: {test_file_path}")

initial_state = create_default_state(local_file_path=test_file_path)
final_state = None

for event in kb_import_app.stream(initial_state):
    for key, value in event.items():
        logger.info(f"节点: {key}")
        final_state = value

logger.info(f"最终状态: {json.dumps(final_state, indent=4, ensure_ascii=False)}")

logger.info("图结构:")
kb_import_app.get_graph().print_ascii()

logger.info("===== 测试结束 =====")
