"""工具函数集"""

from pathlib import Path
from typing import Any
import json


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, tool: dict) -> None:
        """注册一个工具"""
        name = tool["name"]
        self._tools[name] = tool

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """调用工具"""
        if name not in self._tools:
            return {"status": "error", "data": None, "message": f"工具不存在: {name}"}
        try:
            result = self._tools[name]["fn"](**kwargs)
            return {"status": "ok", "data": result}
        except Exception as e:
            return {"status": "error", "data": None, "message": str(e)}

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({', '.join(self._tools.keys())})"


# ---------- 内置工具 ----------

def _read_csv(path: str, encoding: str = "utf-8", **kwargs) -> dict:
    """读取 CSV 文件并返回基本信息和 DataFrame"""
    import pandas as pd

    fp = Path(path)
    if not fp.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    df = pd.read_csv(fp, encoding=encoding, **kwargs)
    return {
        "shape": df.shape,
        "columns": list(df.columns),
        "dtypes": {col: str(dt) for col, dt in df.dtypes.items()},
        "head": df.head(10).to_dict(orient="records"),
        "describe": df.describe(include="all").to_dict(),
        "null_counts": df.isnull().sum().to_dict(),
        "dataframe": df,
    }


def _analyze_dataframe(dataframe, **kwargs) -> dict:
    """对 DataFrame 进行基础统计分析"""
    import pandas as pd
    import numpy as np

    df: pd.DataFrame = dataframe
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

    stats = {}
    for col in numeric_cols:
        stats[col] = {
            "mean": float(df[col].mean()) if not df[col].isnull().all() else None,
            "std": float(df[col].std()) if not df[col].isnull().all() else None,
            "min": float(df[col].min()) if not df[col].isnull().all() else None,
            "max": float(df[col].max()) if not df[col].isnull().all() else None,
            "median": float(df[col].median()) if not df[col].isnull().all() else None,
        }

    cat_info = {}
    for col in categorical_cols:
        value_counts = df[col].value_counts().head(10).to_dict()
        cat_info[col] = {
            "unique_count": int(df[col].nunique()),
            "top_values": {str(k): int(v) for k, v in value_counts.items()},
        }

    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "numeric_stats": stats,
        "categorical_info": cat_info,
        "dataframe": df,
    }


def _transform_data(dataframe, **kwargs) -> dict:
    """对 DataFrame 执行常见转换操作"""
    import pandas as pd

    df: pd.DataFrame = dataframe.copy()

    if kwargs.get("dropna"):
        df = df.dropna(**{k: v for k, v in kwargs.items() if k in ("axis", "how", "subset")})

    if "astype" in kwargs:
        df = df.astype(kwargs["astype"])

    if "rename" in kwargs:
        df = df.rename(columns=kwargs["rename"])

    if "sort_by" in kwargs:
        ascending = kwargs.get("ascending", True)
        df = df.sort_values(by=kwargs["sort_by"], ascending=ascending)

    if "query" in kwargs:
        df = df.query(kwargs["query"])

    return {
        "shape": df.shape,
        "columns": list(df.columns),
        "head": df.head(10).to_dict(orient="records"),
        "dataframe": df,
    }


def _save_csv(dataframe, path: str, encoding: str = "utf-8", **kwargs) -> dict:
    """保存 DataFrame 为 CSV"""
    import pandas as pd

    df: pd.DataFrame = dataframe
    fp = Path(path)
    df.to_csv(fp, index=False, encoding=encoding, **kwargs)
    return {"saved_path": str(fp.resolve()), "rows": len(df), "columns": len(df.columns)}


def _export_json(dataframe, path: str | None = None, **kwargs) -> dict:
    """将 DataFrame 导出为 JSON"""
    import pandas as pd

    df: pd.DataFrame = dataframe
    records = df.head(100).to_dict(orient="records")

    if path:
        fp = Path(path)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, default=str)
        return {"saved_path": str(fp.resolve()), "records": len(records)}
    return {"records": records}


default_tools: list[dict[str, Any]] = [
    {"name": "read_csv", "fn": _read_csv, "description": "读取 CSV 文件"},
    {"name": "analyze", "fn": _analyze_dataframe, "description": "数据分析"},
    {"name": "transform", "fn": _transform_data, "description": "数据转换"},
    {"name": "save_csv", "fn": _save_csv, "description": "保存为 CSV"},
    {"name": "export_json", "fn": _export_json, "description": "导出为 JSON"},
]
