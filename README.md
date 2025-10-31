# Guba Comment Scraper (股吧评论抓取工具)

这是一个基于 FastAPI 和 MCP (Machine-Readable Composable Prompts) 框架的工具，用于抓取东方财富股吧中指定股票的最新评论标题。

## ✨ 功能特性

- **实时抓取**: 根据提供的股票代码（如 `sh600739`），从东方财富股吧抓取前5页的帖子标题。
- **MCP 工具集成**: 提供一个名为 `get_guba_comments` 的 MCP 工具，可供 AI Agent 或其他 MCP 客户端调用。
- **API 接口**: 基于 FastAPI 构建，提供一个 `/` 健康检查端点。
- **容器化**: 附带一个生产级别的 `Dockerfile`，支持使用 Docker 轻松部署。
- **健壮性**: 包含了完整的日志记录、请求超时和错误处理机制。

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Docker (推荐)

### 1. 使用 Docker 部署 (推荐)

这是最简单、最可靠的部署方式。

1.  **构建 Docker 镜像:**
    ```bash
    docker build -t guba-scraper .
    ```

2.  **运行 Docker 容器:**
    ```bash
    docker run -d -p 8080:8080 --name guba-app guba-scraper
    ```
    服务现在运行在 `http://localhost:8080`。

3.  **检查服务状态:**
    访问 `http://localhost:8080/`，如果看到 `{"status":"healthy"}` 则表示服务运行正常。

### 2. 本地运行 (用于开发)

1.  **克隆仓库:**
    ```bash
    git clone https://github.com/buuzzy/guba.git
    cd guba
    ```

2.  **创建并激活虚拟环境:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **安装依赖:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **启动服务:**
    ```bash
    uvicorn server:app --host 0.0.0.0 --port 8080
    ```

## 🛠️ 如何使用

该服务通过 MCP 协议暴露其功能。您可以使用任何兼容的 MCP 客户端进行交互。

**工具名称**: `get_guba_comments`

**参数**:
- `stock_code` (str): 股票代码，必须符合 `sh` 或 `sz` + 6位数字的格式。

**示例查询**:

- **查询新华百货 (sh600739) 的评论:**
  ```
  get_guba_comments("sh600739")
  ```

- **查询万科A (sz000002) 的评论:**
  ```
  get_guba_comments("sz000002")
  ```

**返回**:
一个包含所有评论标题的长字符串，标题之间用中文逗号“，”分隔。

## 📝 项目文件结构

- `server.py`: FastAPI 应用和 MCP 工具的核心逻辑。
- `requirements.txt`: 项目所需的 Python 依赖库列表。
- `Dockerfile`: 用于构建和部署应用的 Docker 配置文件。
- `.env` (可选): 可用于配置环境变量，如 `PORT`。