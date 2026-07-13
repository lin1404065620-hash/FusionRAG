"""配置管理"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    """代理配置"""

    name: str = "data-agent"
    """代理名称"""

    workspace: Path = field(default_factory=Path.cwd)
    """工作目录"""

    verbose: bool = False
    """是否输出详细日志"""

    max_history: int = 100
    """最大历史记录数"""

    csv_encoding: str = "utf-8"
    """CSV 文件默认编码"""

    pandas_display_max_rows: int = 20
    """Pandas 最大显示行数"""

    pandas_display_max_columns: int = 10
    """Pandas 最大显示列数"""

    def __post_init__(self):
        if isinstance(self.workspace, str):
            self.workspace = Path(self.workspace)
