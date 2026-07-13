from pathlib import Path
import os


def get_path_dir(ps: int = 0) -> Path:
    """
    pathlib.Path 提供了 parents 属性，通过索引取值快速获取「上 N 级目录」
    parents[0] -> .parent
    parents[1] -> .parent.parent
    以此类推
    :param ps: 向上层级数
    :return: 对应层级的目录 Path
    """
    return Path(__file__).parents[ps]


def get_project_root(identifier: str = ".env") -> Path:
    env_root = os.getenv("PROJECT_ROOT")
    if env_root and Path(env_root).absolute().exists():
        return Path(env_root).absolute()

    current_dir = Path(__file__).absolute().parent
    while current_dir != current_dir.parent:
        if (current_dir / identifier).exists():
            return current_dir
        current_dir = current_dir.parent

    raise FileNotFoundError(f"未找到项目根目录标识「{identifier}」，且环境变量PROJECT_ROOT未配置")


PROJECT_ROOT = get_project_root(".env")