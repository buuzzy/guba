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

# --- V2.0: 新增 SnowNLP 依赖 ---
import snownlp
# --------------------------------

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
            
            if response.status_code != 200:
                logging.warning(f"抓取 {target_url} 失败，状态码: {response.status_code}")
                break 
            
            soup = BeautifulSoup(response.content, 'lxml') # type: ignore
            
            post_rows = soup.find_all('tr', class_='listitem')
            if not post_rows:
                logging.info(f"{normalized_code} 第 {current_page} 页没有找到帖子。")
                break 
                
            comments_found_in_page = 0
            for row in post_rows:
                try:
                    title_div = row.find('div', class_='title')
                    title_link = title_div.find('a') if title_div else None
                    title = title_link.text.strip() if title_link else ''
                    if title: 
                        all_comment_titles.append(title)
                        comments_found_in_page += 1
                except Exception:
                    continue 
            
            logging.info(f"{normalized_code} 第 {current_page} 页抓取 {comments_found_in_page} 条。")
            pages_crawled += 1
            current_page += 1
            
            time.sleep(random.uniform(0.3, 1.0)) 
        
        except requests.exceptions.RequestException as req_err:
            logging.error(f"抓取 {normalized_code} 时网络请求失败: {req_err}")
            raise req_err

    if not all_comment_titles:
        return f"未找到股票 {stock_code} 的任何评论。"
    
    commit_string = "\n".join(all_comment_titles)
    
    logging.info(f"为 {stock_code} 成功抓取 {len(all_comment_titles)} 条评论。")
    return commit_string

# --- V3.0 (最终版): 修改情感分析工具的签名 ---
@mcp.tool()
@guba_tool_handler 
def analyze_guba_sentiment(result: Dict[str, Any]) -> str: # <---【关键修改 1】
    """
    分析以换行符分隔的评论字符串，计算平均情感分数。
    
    Args:
        result: 工作流平台传入的字典, 预期格式: {"result": "评论A\n评论B..."}
    """
    
    # --- 【关键修改 2】: 从传入的字典中提取出字符串 ---
    comments_string = "" # 默认值
    if isinstance(result, dict) and "result" in result:
        comments_string = result.get("result", "")
    elif isinstance(result, str):
        # 兜底：以防平台某天又直接传了字符串
        comments_string = result
    else:
        return f"情感分析节点收到的参数格式错误：需要一个字典 {{'result': '...'}} 或一个字符串，但收到了 {type(result)}"
    # -----------------------------------------------

    if not comments_string or not comments_string.strip():
        return "没有可供分析的评论。"
        
    try:
        # 按换行符分割成列表
        comments = comments_string.strip().split('\n')
        total_score = 0
        valid_comments = 0
        
        logging.info(f"开始分析 {len(comments)} 条评论...")
        
        for comment in comments:
            if comment and comment.strip(): # 确保评论非空
                try:
                    # 使用 snownlp 进行分析
                    s = snownlp.SnowNLP(comment)
                    total_score += s.sentiments
                    valid_comments += 1
                except Exception as e:
                    # 忽略单个评论的分析错误
                    logging.warning(f"SnowNLP 分析单条评论失败: {e} (评论: '{comment[:20]}...')")
                    
        if valid_comments == 0:
            return "评论内容均无效，无法分析。"
            
        average_sentiment = total_score / valid_comments
        
        # 返回一个对 LLM 友好的分析结果
        sentiment_desc = "中性"
        if average_sentiment > 0.6:
            sentiment_desc = "偏积极"
        elif average_sentiment < 0.4:
            sentiment_desc = "偏消极"
            
        result_str = f"分析了 {valid_comments} 条评论，平均情感分数为: {average_sentiment:.4f} ({sentiment_desc})"
        logging.info(result_str)
        return result_str
        
    except Exception as e:
        # 这是整个函数的兜底错误
        logging.error(f"SnowNLP 分析任务出错: {e}", exc_info=True)
        return f"情感分析模块出错: {e}"
# ------------------------------------


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

工具列表：
1. get_guba_comments(stock_code: str)
   抓取评论标题。
   示例: > get_guba_comments("sh600739")

2. analyze_guba_sentiment(result: Dict)
   分析评论情感。
   (此工具用于接收上一步的 {"result": "..."} 对象)
   示例: > analyze_guba_sentiment({"result": "评论A\n评论B"})
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


