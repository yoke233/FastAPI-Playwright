import asyncio
import base64
import os
import platform
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field
from uvicorn import Config, Server


class SearchIn(BaseModel):
    search: bool = False
    search_input_selector: Optional[str] = Field(
        default=None, description="搜索输入框的选择器"
    )
    search_button_selector: Optional[str] = Field(
        default=None, description="搜索按钮的选择器"
    )
    search_term: Optional[str] = Field(default=None, description="搜索关键词")


class ItemsConfig(BaseModel):
    enabled: bool = False
    item_selector: Optional[str] = Field(default=None, description="项目的选择器")
    title_selector: Optional[str] = Field(default=None, description="项目标题的选择器")
    date_selector: Optional[str] = Field(default=None, description="项目日期的选择器")


class BodyConfig(BaseModel):
    enabled: bool = False
    body_selectors: List[str] = Field(
        default_factory=list, description="正文内容的选择器列表"
    )
    title_selectors: List[str] = Field(
        default_factory=list, description="标题内容的选择器列表"
    )
    date_selectors: List[str] = Field(
        default_factory=list, description="日期内容的选择器列表"
    )


class RequestBody(BaseModel):
    url: str
    browser: str = Field(
        default="chromium",
        description="要使用的浏览器类型: 'chromium', 'firefox', 或 'webkit'",
    )
    screenshot: bool = False
    search_in: SearchIn = SearchIn()
    items_config: ItemsConfig = ItemsConfig()
    body_config: BodyConfig = BodyConfig()


async def wait_for_network_idle(page, timeout):
    try:
        await asyncio.wait_for(page.wait_for_load_state("networkidle"), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"在 {timeout} 秒内未达到网络空闲状态，继续执行...")


def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024**2:
        return f"{size / 1024:.2f} KB"
    elif size < 1024**3:
        return f"{size / 1024 ** 2:.2f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


async def capture_screenshot(page):
    screenshot = await page.screenshot()
    screenshot_size = len(screenshot)
    formatted_size = format_size(screenshot_size)
    screenshot_base64 = base64.b64encode(screenshot).decode("utf-8")
    return {"size": formatted_size, "base64": screenshot_base64}


async def get_items_content(
    page, item_selector, title_selector=None, date_selector=None
):
    await page.wait_for_selector(item_selector, timeout=10000)
    items = await page.query_selector_all(item_selector)
    items_content = []
    for item in items:
        item_content = {}

        if title_selector:
            title_element = await item.query_selector(title_selector)
            if title_element:
                item_content["title"] = (
                    (await title_element.text_content()).replace("\n", " ").strip()
                )
            else:
                item_content["title"] = ""

        link_elements = await item.query_selector_all("a")
        if link_elements:
            item_content["links"] = [
                await link.get_attribute("href") for link in link_elements
            ]
        else:
            item_content["links"] = [""]

        if date_selector:
            date_element = await item.query_selector(date_selector)
            if date_element:
                item_content["date"] = (
                    (await date_element.text_content()).replace("\n", " ").strip()
                )
            else:
                item_content["date"] = "无日期"

        items_content.append(item_content)
    return items_content


async def get_content_by_selectors(page, selectors):
    results = []
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            element = await page.query_selector(selector)
            if element:
                content = (await element.text_content()).replace("\n", " ").strip()
                results.append({"selector": selector, "content": content})
        except PlaywrightTimeoutError:
            results.append({"selector": selector, "content": None})
    return results


async def get_body_content(page, body_selectors, title_selectors, date_selectors):
    if body_selectors:
        body_content = await get_content_by_selectors(page, body_selectors)
    else:
        all_text = await page.content()
        body_content = [{"selector": None, "content": all_text}]
    title_content = (
        await get_content_by_selectors(page, title_selectors)
        if title_selectors
        else [{"selector": None, "content": ""}]
    )
    date_content = (
        await get_content_by_selectors(page, date_selectors)
        if date_selectors
        else [{"selector": None, "content": ""}]
    )

    return {"title": title_content, "body": body_content, "date": date_content}


async def get_meta(page):

    # 获取所有的 <meta> 标签
    meta_tags = await page.query_selector_all("meta")
    # print(meta_tags)
    meta_info = {}

    for tag in meta_tags:
        name = await tag.get_attribute("name")
        property_attr = await tag.get_attribute("property")
        content = await tag.get_attribute("content")

        if name == "description" or property_attr == "og:description":
            meta_info["description"] = content
        elif name == "keywords" or property_attr == "og:keywords":
            meta_info["keywords"] = content
        elif property_attr == "og:title":
            meta_info["title"] = content
    return meta_info


async def restart_browser(browser_type, app):
    """重启浏览器实例"""
    p = app.state.playwright
    use_browser = getattr(p, browser_type, None)
    new_browser = await use_browser.launch(headless=True)
    app.state.browser_instances[browser_type] = new_browser
    return new_browser


async def get_page_info(request_data: RequestBody, request: Request):

    page_info = {}
    browser_type = request_data.browser

    if browser_type not in ["chromium", "firefox", "webkit"]:
        raise HTTPException(status_code=400, detail="无效的浏览器类型")

    # 如果还没有启动该类型的浏览器，则启动它
    if browser_type not in app.state.browser_instances:
        p = request.app.state.playwright
        use_browser = getattr(p, browser_type, None)
        browser = await use_browser.launch(headless=True)
        app.state.browser_instances[browser_type] = browser
    else:
        browser = app.state.browser_instances[browser_type]

    if browser.is_connected() == False:
        print("浏览器连接已断开，正在重启...")
        browser = await restart_browser(browser_type, app)

    page = await browser.new_page()

    await page.goto(request_data.url)

    page_info["meta"] = await get_meta(page)

    if request_data.search_in.search:
        try:
            await page.fill(
                request_data.search_in.search_input_selector,
                request_data.search_in.search_term,
            )
            await page.click(request_data.search_in.search_button_selector)
        except Exception as e:
            print(f"搜索操作失败: {e}")

    await wait_for_network_idle(page, timeout=10)

    if request_data.items_config.enabled and request_data.body_config.enabled:
        raise HTTPException(status_code=400, detail="列表页和详情页配置只能启用一个")

    if request_data.items_config.enabled:
        try:
            page_info["items"] = await get_items_content(
                page,
                request_data.items_config.item_selector,
                request_data.items_config.title_selector,
                request_data.items_config.date_selector,
            )
        except PlaywrightTimeoutError:
            page_info["items"] = []

    if request_data.body_config.enabled:
        page_info["body"] = await get_body_content(
            page,
            request_data.body_config.body_selectors,
            request_data.body_config.title_selectors,
            request_data.body_config.date_selectors,
        )

    if request_data.screenshot:
        page_info["screenshot"] = await capture_screenshot(page)

    await page.close()
    return page_info


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_playwright() as p:
        app.state.playwright = p
        app.state.browser_instances = {}
        print("Initialized browser_instances")  # 确认初始化

        yield  # 先保留 playwright 实例

        # 在应用关闭时关闭所有浏览器实例
        for browser in app.state.browser_instances.values():
            await browser.close()


app = FastAPI(lifespan=lifespan)


@app.post("/capture")
async def capture(request_data: RequestBody, request: Request):
    if not request_data.url:
        raise HTTPException(status_code=400, detail="URL是必须的")
    if request_data.items_config.enabled and request_data.body_config.enabled:
        raise HTTPException(status_code=400, detail="列表页和详情页配置只能启用一个")
    page_info = await get_page_info(request_data, request=request)
    return JSONResponse(content=page_info)


def run_server():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    config = Config(app=app, host=host, port=port, reload=True)

    if platform.system() == "Windows":
        from asyncio.windows_events import ProactorEventLoop

        loop = ProactorEventLoop()
        asyncio.set_event_loop(loop)
    else:
        loop = asyncio.get_event_loop()

    server = Server(config=config)

    try:
        loop.run_until_complete(server.serve())
    except KeyboardInterrupt:
        print("程序结束运行中.....")
    finally:
        loop.run_until_complete(server.shutdown())
        loop.close()


if __name__ == "__main__":
    run_server()
