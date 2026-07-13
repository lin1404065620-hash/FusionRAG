# FusionRAG

基于 RAG 的多源融合智能问答系统，支持 PDF 文档导入、多路检索（语义搜索 + HyDE + 联网搜索）、RRF 融合排序及流式图片关联回答。

## 架构概览

```
用户提问 → LLM 实体抽取 + 改写
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
 语义搜索   HyDE搜索   MCP联网搜索
    │         │         │
    └─────────┼─────────┘
              ▼
         RRF 分数融合
              │
              ▼
      Cross-Encoder 精排
              │
              ▼
         流式 SSE 回答（含图片）
```

## 功能特性

- **PDF 智能解析**：MinerU API 将 PDF 转换为 Markdown，保留文档结构
- **图片视觉理解**：VL 模型对文档图片生成描述，MinIO 存储图片
- **混合向量化**：BGE-M3 生成稠密（1024 维）+ 稀疏向量，HNSW 索引
- **商品实体识别**：LLM 自动识别文档主体，支持按商品名过滤检索
- **三路并行召回**：语义搜索 + HyDE 假设文档 + MCP 联网搜索
- **RRF 融合**：Reciprocal Rank Fusion（K=60）跨路合并排序
- **Cross-Encoder 精排**：BGE-Reranker 重排序 + 动态断崖截断
- **流式 SSE 输出**：实时增量生成答案，关联图片展示

## 技术栈

| 模块 | 技术 |
|------|------|
| 编排框架 | LangGraph |
| 向量数据库 | Milvus（HNSW + SPARSE_INVERTED_INDEX） |
| 嵌入模型 | BGE-M3（1024 维稠密 + 稀疏） |
| 重排序 | BGE-Reranker（Cross-Encoder） |
| 对象存储 | MinIO |
| 大模型 | 兼容 OpenAI API（DashScope / DeepSeek 等） |
| 文档解析 | MinerU API |
| Web 搜索 | MCP 协议 + 百炼搜索 |
| API 服务 | FastAPI + SSE |
| 前端 | 原生 HTML/CSS/JS |

## 项目结构

```
FusionRAG/
├── app/
│   ├── clients/         # Milvus / MinIO / MongoDB / Neo4j 客户端
│   ├── conf/            # 配置类（环境变量读取）
│   ├── core/            # 日志 / 提示词加载
│   ├── lm/              # LLM / Embedding / Reranker 单例管理
│   ├── utils/           # 工具函数
│   ├── import_process/  # 文档导入流水线（7 节点）
│   │   ├── agent/       # LangGraph 节点定义
│   │   ├── api/         # FastAPI 导入服务
│   │   └── page/        # 上传页面
│   ├── query_process/   # 智能问答流水线（7 节点）
│   │   ├── agent/       # LangGraph 节点定义
│   │   ├── api/         # FastAPI 查询服务 + SSE
│   │   ├── page/        # 聊天页面
│   │   └── sse/         # SSE 测试页面
│   ├── test/            # 测试脚本
│   └── tool/            # 模型下载工具
├── prompts/             # 提示词模板
├── src/                 # 数据处理 Agent
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── start_all.bat        # 一键启动脚本
└── import_only.bat      # 数据导入脚本
```

## 快速开始

### 环境要求

- Python 3.10+
- Milvus（本地或远程）
- MinIO（图片存储）
- MongoDB（聊天历史，可选）
- BGE-M3 模型权重

### 安装

```bash
# 克隆仓库
git clone https://github.com/lin1404065620-hash/FusionRAG.git
cd FusionRAG

# 安装依赖
pip install -e .

# 下载嵌入模型
python app/tool/download_bgem3.py

# 下载重排序模型
python app/tool/download_reranker.py
```

### 配置

复制环境变量模板并填写实际值：

```bash
cp .env.example .env
# 编辑 .env 填写 API Key 和服务地址
```

### 启动

```bash
# Windows 一键启动（MongoDB + MinIO + 查询服务）
start_all.bat

# 或手动启动查询服务
python -m app.query_process.api.query_server

# 导入文档
python -m app.import_process.api.import_server
```

浏览器打开 `http://127.0.0.1:8001/chat.html` 即可使用。

## License

MIT
