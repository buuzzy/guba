import os
import sys
import re
import logging
import functools
from typing import Optional, Dict, Any, Callable, List

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
from mcp.server.sse import SseServerTransport

# 抓取逻辑所需的额外库
import requests
import time
import random
from bs4 import BeautifulSoup

# --- 1. 日志配置 (同 server.py) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

# --- 2. 错误处理装饰器 (参照 server.py 风格) ---
def guba_tool_handler(func: Callable) -> Callable:
    """统一处理 Guba 抓取工具的错误和日志"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logging.info(f"调用工具: {func.__name__}，参数: {kwargs}")
        try:
            # 执行工具函数
            return func(*args, **kwargs)
        except requests.exceptions.Timeout:
            logging.error(f"Guba 抓取超时: {kwargs}", exc_info=True)
            return "抓取超时：无法连接到股吧服务器"
        except requests.exceptions.RequestException as e:
            logging.error(f"Guba 抓取网络错误: {e}", exc_info=True)
            return f"抓取失败：网络错误 {str(e)}"
        except Exception as e:
            logging.error(f"Guba 抓取未知错误: {e}", exc_info=True)
            return f"抓取失败: {str(e)}"
    return wrapper

# --- 3. 初始化 ---
load_dotenv()
PORT = int(os.environ.get("PORT", 8080))

# --- 从 guba.py 引入的配置项 ---
GUBA_LIST_URL_FORMAT = "https://guba.eastmoney.com/list,{stock_code}_{page}.html"
HEADERS = {
    'User-Agent': 'Mozilla.5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8', 'Connection': 'keep-alive',
    'Referer': 'https://guba.eastmoney.com/'
}
DEFAULT_PAGES_TO_SCRAPE = 5 # 抓取 5 页
# --------------------------------

logging.info("Guba MCP 服务配置加载完毕")

# FastAPI & MCP 初始化
app = FastAPI(
    title="股吧评论抓取工具",
    version="1.0.0",
    description="抓取指定股票前5页股吧评论标题的工具"
)
mcp = FastMCP("Guba Comment Scraper")

def normalize_stock_code(code: str) -> Optional[str]:
    """(同 server.py) 验证股票代码格式是否符合标准 (sh600739 或 sz301011)"""
    code = code.strip().lower()
    if re.match(r'^(sh|sz)\d{6}$', code):
        return code
    return None

# --- 4. 核心工具逻辑 ---
@mcp.tool()
@guba_tool_handler
def get_guba_comments(stock_code: str) -> str:
    """抓取股吧前5页评论标题
    
    Args:
        stock_code: 股票代码，如 'sh600739' 或 'sz301011'
        
    Returns:
        一个包含所有评论标题的字符串，以换行符（\n）分隔。
    """
    if not (normalized_code := normalize_stock_code(stock_code)):
        return f"股票代码格式错误：'{stock_code}'。请使用标准格式，如：sh600739 或 sz301011"
    
    # 股吧 URL 需要 6 位数字代码
    guba_code = normalized_code[2:]
    
    session = requests.Session()
    session.headers.update(HEADERS)
    current_page = 1
    pages_crawled = 0
    all_comment_titles: List[str] = []
    
    logging.info(f"开始为 {normalized_code} (Guba: {guba_code}) 抓取评论...")
    
    while pages_crawled < DEFAULT_PAGES_TO_SCRAPE:
        target_url = GUBA_LIST_URL_FORMAT.format(stock_code=guba_code, page=current_page)
        
        try:
            response = session.get(target_url, timeout=10) # 10 秒超时
            
            # response.encoding = 'gb18030' # <-- 【修复】移除此行!
            
            if response.status_code != 200:
                logging.warning(f"抓取 {target_url} 失败，状态码: {response.status_code}")
                break # 页面抓取失败，停止
            
            # 【修复】使用 response.content (原始字节流)
            # 这让 BeautifulSoup 自己去检测编码 (它通常做得更好，会优先 UTF-8)
            # 而不是依赖 response.text (它可能被错误的 HTTP 头误导)
            
            # Pylance (reportArgumentType) 在此报错是误报，BeautifulSoup 构造函数支持 bytes
            soup = BeautifulSoup(response.content, 'lxml') # type: ignore
            
            post_rows = soup.find_all('tr', class_='listitem')
            if not post_rows:
                logging.info(f"{normalized_code} 第 {current_page} 页没有找到帖子。")
                break # 没有更多帖子，停止
                
            comments_found_in_page = 0
            for row in post_rows:
                try:
                    # 仅提取标题
                    title_div = row.find('div', class_='title')
                    title_link = title_div.find('a') if title_div else None
                    title = title_link.text.strip() if title_link else ''
                    if title: # 仅添加非空标题
                        all_comment_titles.append(title)
                        comments_found_in_page += 1
                except Exception:
                    continue # 忽略解析失败的单行
            
            logging.info(f"{normalized_code} 第 {current_page} 页抓取 {comments_found_in_page} 条。")
            pages_crawled += 1
            current_page += 1
            
            # 礼貌性暂停
            time.sleep(random.uniform(0.3, 1.0)) 
        
        except requests.exceptions.RequestException as req_err:
            logging.error(f"抓取 {normalized_code} 时网络请求失败: {req_err}")
            # 抛出异常，让 @guba_tool_handler 装饰器统一处理
            raise req_err

    if not all_comment_titles:
        return f"未找到股票 {stock_code} 的任何评论。"
    
    # 【重要修改】使用换行符 \n 作为分隔符，这对于 LLM 分析更友好
    commit_string = "\n".join(all_comment_titles)
    
    logging.info(f"为 {stock_code} 成功抓取 {len(all_comment_titles)} 条评论。")
    return commit_string

# --- 5. FastAPI 和 MCP SSE 集成 (同 server.py) ---
@app.get("/")
async def health_check() -> Dict[str, str]:
    """健康检查端点"""
    return {"status": "healthy"}

# MCP SSE 集成 (参考 demo.py 的最终修正版)
MCP_BASE_PATH = "/sse"
try:
    messages_full_path = f"{MCP_BASE_PATH}/messages/"
    sse_transport = SseServerTransport(messages_full_path)

    async def handle_mcp_sse_handshake(request: Request) -> None:
        """
        处理 MCP 的 SSE 握手。
        此函数不返回任何值，因为 sse_transport 会完全接管响应流。
        """
        async with sse_transport.connect_sse(
            request.scope, 
            request.receive, 
            request._send
        ) as (read_stream, write_stream):
            await mcp._mcp_server.run(
                read_stream, 
                write_stream, 
                mcp._mcp_server.create_initialization_options()
            )

    @mcp.prompt()
    def usage_guide() -> str:
        """提供使用指南"""
        return """欢迎使用股吧评论抓取工具！

股票代码格式说明：
- 上海证券交易所：sh + 6位数字，如 sh600739
- 深圳证券交易所：sz + 6位数字，如 sz301011

示例查询：
> get_guba_comments("sh600739")  # 新华百货
> get_guba_comments("sz000002")  # 万科A
"""

    # 注册路由
    app.add_route(MCP_BASE_PATH, handle_mcp_sse_handshake, methods=["GET"])  # type: ignore
    app.mount(messages_full_path, sse_transport.handle_post_message)
    
    logging.info("MCP SSE 集成设置完成")

except Exception as e:
    logging.critical(f"应用 MCP SSE 设置时发生严重错误: {e}", exc_info=True)
    sys.exit(1)

# --- 6. 启动入口 (同 server.py) ---
if __name__ == "__main__":
    logging.info(f"启动服务器，监听端口: {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)

