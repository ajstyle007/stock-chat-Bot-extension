from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import json
import logging
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from fastapi.responses import JSONResponse
from pydantic import BaseModel as PydanticBaseModel, Field
from sel import get_driver, scrape_stocks, click_element, scrape_single_stock, scrape_stock_news, scrape_sector, display_stock_chart 

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
api_key = os.getenv("GOOGLE_GEMINI_KEY")
if not api_key:
    logger.error("GOOGLE_GEMINI_KEY environment variable not set")
    raise ValueError("GOOGLE_GEMINI_KEY environment variable not set")

# Initialize FastAPI app
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define request model
class Query(BaseModel):
    prompt: str

# Initialize LangChain Gemini model
try:
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-pro",
        google_api_key=api_key,
        temperature=0.2,
        max_output_tokens=1000
    )
except Exception as e:
    logger.error(f"Failed to initialize Gemini model with LangChain: {str(e)}")
    raise

# Define LangChain output model for actions
class Action(PydanticBaseModel):
    action: str = Field(description="The action to perform (e.g., navigate, click, extract, display_chart)")
    selector: str = Field(description="CSS selector for the element", default="")
    url: str = Field(description="URL for navigation", default="")
    count: int = Field(description="Number of elements to extract", default=0)
    ticker: str = Field(description="Stock ticker for chart display", default="")
    timeframe: str = Field(description="Timeframe for chart display", default="1Y")

class ActionsResponse(PydanticBaseModel):
    actions: list[Action] = Field(description="List of actions to perform", default=[])
    actions_single: list[Action] = Field(description="List of actions for single stock", default=[])
    actions_news: list[Action] = Field(description="List of actions for news", default=[])
    action_sector: list[Action] = Field(description="List of actions for sector data", default=[])
    actions_chart: list[Action] = Field(description="List of actions for chart display", default=[])
    message: str = Field(description="Optional message for invalid prompts", default="")

prompt_template = PromptTemplate(
    input_variables=["user_prompt"],
    template="""
    You are an assistant integrated with a system that scrapes stock data from TradingView using selenium.

    Given the user prompt: '{user_prompt}', respond with ONLY a valid JSON object.
    Do not include code fences, explanations, or extra text — just pure JSON.

    General Instructions:
    - Analyze the user prompt to determine intent.
    - Supported actions: "navigate", "navigate_single", "extract", "extract_single", "click", "type".
    - Return an array of actions in execution order.
    - Use "navigate" and "extract" for multiple stocks; use "navigate_single" and "extract_single" for single stock details.
    - Handle dynamic page loading with appropriate selectors and WebDriverWait conditions.
    - For invalid or ambiguous prompts, return {{"actions": []}} with an optional "message" field.

    Stock Ticker Mapping (examples):
    - "Apple" -> "AAPL"
    - "Microsoft" -> "MSFT"
    - "Google" -> "GOOGL"
    -" Amazon" -> "AMZN"
    - "Tesla" -> "TSLA"
    - "NVIDIA" -> "NVDA"
    - "INFOSYS" -> "INFY"
    - "Netflix" -> "NFLX"
    etc.
    - If ticker is unknown, use search action with "type" and "click".

    Specific Cases:

    1. **Best Performing Stock in Portfolio**
       - Navigate to: "https://www.tradingview.com/markets/stocks-usa/market-movers-gainers/"
       - Extract rows: "table[class*='market-table'] tbody tr"
       - Extract fields: ticker ("td[class*='ticker'] a"), price ("td[class*='last']"), change_percent ("td[class*='change']"), volume ("td[class*='volume']")
       - Identify stock with highest positive percentage change.
       - Click ticker link: "td[class*='ticker'] a" for the best stock.

    2. **Worst Performing Stock(s)**
       - Navigate to: "https://www.tradingview.com/markets/stocks-usa/market-movers-losers/"
       - Extract rows: "table[class*='market-table'] tbody tr"
       - Extract fields: ticker ("td[class*='ticker'] a"), price ("td[class*='last']"), change_percent ("td[class*='change']"), volume ("td[class*='volume']")
       - If user specifies a number (e.g., "worst 4 stocks"), set "count" to that number; default to 10 if unspecified.
       - Sort by lowest percentage change.

    3. **Single Stock Details**
        - If user specifies a stock (e.g., "show Apple stock"), map to ticker (e.g., "AAPL") or use search if unknown.
        - Navigate to: "https://www.tradingview.com/symbols/{{STOCK_TICKER}}/"
        - Extract fields:
            - symbol: ("h1.apply-overflow-tooltip")
            - price: ("span.js-symbol-last")
            - performance: loop over "span.content-o1CQs_Mg", extract inner spans:
                - First span = timeframe label (e.g., "1 day", "5 days", "1 month", "6 months", "Year to date", "1 year", "5 years", "All time")
                - Second span = (corresponding % change)
        - If ticker is invalid, return {{"actions": [], "message": "Invalid stock ticker"}}.

    4. **Search for Stock**
       - Type stock name/ticker into: "input[name='query']"
       - Click search result: "a[class*='search-result']"

    5. **Clicking a Stock in Portfolio**
       - Use selector: "td[class*='ticker'] a" with correct row index for specific stock.

    6. **Unrelated or Invalid Prompts**
       - Return {{"actions": [], "message": "No relevant stock actions found"}}.

    7. **Stock News**
        If the user asks for news a bout a s pecific stock (e.g., 'latest news on Apple' or 'MSFT news'):
        1. Map the stock name to its ticker (e.g., Apple → AAPL).
        2. Navigate to the stock news page: 'ht tps://www.tradingview.com/symbols/{{STOCK_TICKER}}/news/'.
        3. Extract the top N news articles (default 5) with the following fields:
            - title: 'a.tv-widget-news__title'
            - link: 'a.tv-widget-news__title' (href attribute)
            - time: 'span.tv-widget-news__time'
        4. If the user specifies a 'count', extract that number of articles.
        If the ticker is invalid or unknown, return:
        {{{{"actions": [], "message": "Invalid stock ticker for news"}}}}.


    8. **Stock Chart and graph Display Requests**
       If the user asks to display a stock chart or graph with a specific timeframe (e.g., "show me Apple stock chart for 1 year", "Tesla chart 6 months", "MSFT 1M chart"):
       1. Map the stock name to its ticker (e.g., Apple → AAPL).
       2. Identify the timeframe (e.g., "1 year" → "12M", "6 months" → "6M", "1 month" → "1M", "5 years" → "60M").
       3. If timeframe is unspecified, default to "1Y".
       4. Return an actions_chart array with "display_chart" action.
       If the ticker is invalid or unknown, return: {{"actions": [], "message": "Invalid stock ticker for chart"}}

       Example (Apple Chart and graph for 1 Year):
       {{
           "actions_chart": [
               {{
                   "action": "display_chart",
                   "ticker": "AAPL",
                   "timeframe": "12M"
               }}
           ]
       }}

    9. **Sector Data**
       If the user asks about different stock sectors like Technology, Energy, Finance, etc.:
       1. Identify the correct sector name from the user's query (match against valid TradingView sectors).
       2. Respond with an action to fetch that sector's data. If user asks for top N, include "count".
       Valid sectors: ["Commercial services", "Communications", "Consumer durables", "Consumer non-durables", 
       "Consumer services", "Distribution services", "Electronic technology", "Energy minerals", "Finance", 
       "Government", "Health services", "Health technology", "Industrial services", "Miscellaneous", 
       "Non-energy minerals", "Process industries", "Producer manufacturing", "Retail trade", "Technology services", "Transportation", "Utilities"]

       Example (All Technology Stocks):
       {{
           "action_sector": [
               {{
                   "action": "fetch_sector_data",
                   "sector": "Technology services",
                   "count": "all"
               }}
           ]
       }}

    Example (Best Performing Stock):
    {{
        "actions": [
            {{"action": "navigate", "url": "https://www.tradingview.com/markets/stocks-usa/market-movers-gainers/"}},
            {{"action": "extract", "selector": "table[class*='market-table'] tbody tr", "count": 10, "fields": {{"ticker": "td[class*='ticker'] a", "price": "td[class*='last']", "change_percent": "td[class*='change']", "volume": "td[class*='volume']"}}}},
            {{"action": "click", "selector": "td[class*='ticker'] a"}}
        ]
    }}

    Example (Least Performing Stock):
    {{
        "actions": [
            {{"action": "navigate", "url": "https://www.tradingview.com/markets/stocks-usa/market-movers-losers/"}},
            {{"action": "extract", "selector": "table[class*='market-table'] tbody tr", "count": 10, "fields": {{"ticker": "td[class*='ticker'] a", "price": "td[class*='last']", "change_percent": "td[class*='change']", "volume": "td[class*='volume']"}}}},
            {{"action": "click", "selector": "td[class*='ticker'] a"}}
        ]
    }}

    Example (Single Stock - Apple):
    {{
        "actions_single": [
            {{"action": "navigate_single", "url": "https://www.tradingview.com/symbols/AAPL/"}},
            {{"action": "extract_single", "selector": "body", "fields": {{"symbol": "h1.apply-overflow-tooltip", "price": "span.js-symbol-last", "performance": "span.content-o1CQs_Mg"}}}}
        ]
    }}

    Example (Search for Unknown Stock):
    {{
        "actions": [
            {{"action": "navigate", "url": "https://www.tradingview.com/"}},
            {{"action": "type", "selector": "input[name='query']", "value": "{{user_prompt}}"}},
            {{"action": "click", "selector": "a[class*='search-result']"}}
        ]
    }}

    Example (Latest 3 News on Apple):
    {{
        "actions_news": [
            {{
                "action": "fetch_stock_news",
                "url": "https://www.tradingview.com/symbols/AAPL/news/",
                "symbol": "AAPL",
                "count": 3
            }}
        ]
    }}

    Return ONLY the JSON object for the given prompt.
    """
)

# Create LangChain chain
parser = JsonOutputParser(pydantic_object=ActionsResponse)
chain = prompt_template | llm | parser

@app.get("/")
async def root():
    return {"message": "TradingView FastAPI is running"}

@app.post("/llm_refine")
async def llm_refine(request: Query):
    """
    Endpoint that first calls /llm_action, then refines its response using the LLM.
    """
    try:
        # Step 1: Get the raw structured output from /llm_action
        raw_output = await llm_action(request)

        # Step 2: Prepare refinement prompt for the LLM
        refine_prompt = f"""
            You are EyeOnStox, a stock assistant created by Rawat Ji and Rathour Saab.
            who is given data from trading view website you analyze that data and answer from that data only.
            Do not use you own knowledge, only use the data provided. and don't answer anything unrelated. 
            The user asked: '{request.prompt}'
            Here is the structured system response provided:

            {json.dumps(raw_output, indent=2)}
            If it's normal greeting or chitchat then respond in a friendly manner but don't guess any values.
            If its a unrelated question, then respond in a friendly manner.
            Your task:
            1. Convert this structured response into a **clear, concise, human-friendly message**.
            2. If there is **stock or crypto data**:
               - Summarize key details (price, change, volume) in bullet points or a simple table.
            3. If there is **performance history**:
               - Present it clearly (e.g., 1D, 1M, 1Y) in a table or bullet points.
            4. If there are **news headlines**:
               - List them cleanly with bullets, showing date if available.
            5. If there is only a **message, info, or error**, present it directly and clearly.
            6. If multiple types of information are present (e.g., stock + news + performance):
               - Separate them with clear headings like **Stock Info**, **Performance**, **News**.
            7. Avoid repeating raw JSON; only summarize meaningful content.
            8. Keep it short, readable, and human-friendly.
            9. If there is **chart display data** (with "status" and "message"):
               - Display the message (e.g., "Displaying AAPL chart for 1Y. Close the browser manually.").
               - Do not mention base64 or expect image data.

            Output format example (if multiple types exist):

            **Stock Info:**
            - Tesla: $1234 (+2.3%)

            **Performance History:**
            - 1D: +2%, 1M: +5%, 1Y: +45%

            **News Headlines:**
            - Headline 1
            - Headline 2

            **Stock Chart:**
            - Displaying {{ticker}} ({{timeframe}}) chart. Close the browser manually.

            If the data is not available, say "Data not available".
        """

        refined = llm.invoke(refine_prompt)

        # Step 3: Return refined response along with original data
        return JSONResponse(content={
            "refined_message": refined.content,
            "raw_output": raw_output
        })

    except Exception as e:
        logger.error(f"LLM refinement error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to refine response: {str(e)}")

@app.post("/llm_action")
async def llm_action(request: Query):
    try:
        # Use LangChain chain to generate actions
        actions_data = chain.invoke({"user_prompt": request.prompt})
        logger.info(f"LangChain LLM response: {json.dumps(actions_data, indent=2)}")

        actions = actions_data.get("actions", [])
        actions_single = actions_data.get("actions_single", [])
        actions_news = actions_data.get("actions_news", [])
        actions_sector = actions_data.get("action_sector", [])
        actions_chart = actions_data.get("actions_chart", [])
        message = actions_data.get("message", "")

        # Check if no valid actions were generated
        if not (actions or actions_single or actions_news or actions_sector or actions_chart):
            logger.warning(f"No valid actions generated for prompt: '{request.prompt}'")
            return {
                "message": message or f"No relevant stock actions found for '{request.prompt}'",
                "stocks": [],
                "news": [],
                "data": [],
                "chart": None
            }

        if actions_single:
            logger.info("Routing to /single_stock endpoint")
            return await get_single_stock(request)
        elif actions:
            logger.info("Routing to /stocks endpoint")
            return await get_stocks(request)
        elif actions_chart:
            logger.info("Routing to /stock_chart endpoint")
            chart_action = actions_chart[0]
            ticker = chart_action.get("ticker")
            timeframe = chart_action.get("timeframe", "1Y")
            return await get_stock_chart(ticker=ticker, timeframe=timeframe)
        elif actions_news:
            logger.info("Routing to /stock_news endpoint")
            stock_name = actions_news[0].get("symbol")
            count = actions_news[0].get("count", 5)
            url = actions_news[0].get("url")
            return await fetch_stock_news(stock=stock_name, url=url, count=count)
        elif actions_sector:
            logger.info("Routing to /sector endpoint")
            sector_name = actions_sector[0].get("sector")
            count = actions_sector[0].get("count", 20)
            return await fetch_sector_data(sector=sector_name, count=count)
        else:
            logger.warning("No valid actions found in response")
            return {
                "message": message or f"No relevant stock actions found for '{request.prompt}'",
                "stocks": [],
                "news": [],
                "data": [],
                "chart": None
            }

    except Exception as e:
        logger.error(f"LLM action routing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to route request: {str(e)}")

@app.post("/stocks")
async def get_stocks(request: Query):
    driver = None
    try:
        # Use LangChain chain to generate actions
        actions_data = chain.invoke({"user_prompt": request.prompt})
        actions = actions_data.get("actions", [])
        logger.info(f"LangChain LLM response: {json.dumps(actions_data, indent=2)}")

        if not actions:
            logger.warning("No actions generated by LangChain")
            generic_response = llm.invoke(request.prompt)
            return {"message": generic_response.content, "stocks": []}

        # Initialize driver
        driver = get_driver()
        driver.get("about:blank")  # Test responsiveness

        # Execute actions and collect stock data
        stocks = []
        best_stock = None
        best_change = float('-inf')
        best_selector = None

        for action in actions:
            if action["action"] == "navigate":
                logger.info(f"Navigating to {action['url']}")
                driver.get(action['url'])

                try:
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "a[class*='tickerNameBox']")
                        )
                    )
                except TimeoutException as e:
                    logger.error(f"Timeout waiting for ticker elements: {str(e)}")
                    return {"message": "Failed to load stock data: Timeout", "stocks": []}

            elif action["action"] == "extract":
                try:
                    stocks = scrape_stocks(
                        driver,
                        row_selector="table tbody tr",
                        ticker_selector="a[href*='/symbols/']",
                        price_selector="td:nth-child(3)",
                        change_percent_selector="td:nth-child(2)",
                        volume_selector="td:nth-child(4)",
                        max_stocks=action.get("count", 0) or 100
                    )
                    logger.info(f"Scraped {len(stocks)} rows: {stocks}")

                    # Find best performing stock
                    for stock in stocks:
                        try:
                            change_percent = float(stock["change_percent"].strip('%').replace('+', ''))
                            if change_percent > best_change:
                                best_change = change_percent
                                best_stock = stock
                                best_selector = (
                                    f"table[class*='portfolio'] tbody tr:nth-child("
                                    f"{stocks.index(stock) + 1}) td[class*='symbol'] a"
                                )
                        except (ValueError, AttributeError) as e:
                            logger.warning(
                                f"Failed to parse change_percent for "
                                f"{stock.get('ticker', 'unknown')}: {str(e)}"
                            )
                            continue

                except Exception as e:
                    logger.error(f"Error in scrape_stocks: {str(e)}")
                    return {
                        "message": f"Failed to scrape stock data: {str(e)}",
                        "stocks": []
                    }

            elif action["action"] == "click" and best_selector:
                result = click_element(driver, best_selector)
                actions.append(result)

        # Prepare response
        if stocks:
            formatted_stocks = [
                {
                    "Ticker": s["ticker"],
                    "Price": s["price"],
                    "Change": s.get("change_percent", "undefined"),
                    "Volume": s.get("volume", "undefined")
                }
                for s in stocks
            ]

            table_text = "\n".join([
                f"{s['Ticker']}: Price: {s['Price']}, Change: {s['Change']}, Volume: {s['Volume']}"
                for s in formatted_stocks
            ])

            response = {
                "message": (
                    f"Top Stocks:\n{table_text}\n\n"
                    f"Best performing: "
                    f"{best_stock['ticker'] if best_stock else formatted_stocks[0]['Ticker']} "
                    f"(+{best_change if best_stock else 'N/A'}%)"
                ),
                "stocks": formatted_stocks
            }
            logger.info(f"Returning response: {json.dumps(response, indent=2)}")
            return response
        else:
            logger.warning("No stocks scraped")
            return {"message": "No valid stock data found", "stocks": []}

    except TimeoutException as e:
        logger.error(f"Timeout scraping portfolio data: {str(e)}")
        return {"message": f"Timeout scraping portfolio data: {str(e)}", "stocks": []}

    except NoSuchElementException as e:
        logger.error(f"Element not found during scraping: {str(e)}")
        return {"message": f"Element not found during scraping: {str(e)}", "stocks": []}

    except Exception as e:
        logger.error(f"Stocks endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.warning(f"Failed to quit driver: {str(e)}")

@app.post("/single_stock")
async def get_single_stock(request: Query):
    driver = None
    try:
        # Use LangChain chain to generate actions
        actions_data = chain.invoke({"user_prompt": request.prompt})
        actions = actions_data.get("actions_single", [])
        logger.info(f"LangChain LLM response: {json.dumps(actions_data, indent=2)}")

        if not actions:
            logger.warning("No single stock actions generated by LangChain")
            generic_response = llm.invoke(request.prompt)
            return {"message": generic_response.content, "stocks": []}

        # Initialize driver
        driver = get_driver()
        driver.get("about:blank")  # Test responsiveness

        for action in actions:
            if action["action"] == "navigate_single":
                logger.info(f"Navigating to {action['url']}")
                driver.get(action['url'])

                try:
                    # First check if single-stock header is present
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "h1.apply-overflow-tooltip")
                        )
                    )
                    logger.info("Single stock page detected.")
                except TimeoutException:
                    try:
                        # Fall back to portfolio table selector
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "a[class*='tickerNameBox']")
                            )
                        )
                        logger.info("Portfolio page detected.")
                    except TimeoutException as e:
                        logger.error(f"Timeout waiting for page content: {str(e)}")
                        return {"message": "Failed to load stock data: Timeout", "stocks": []}

            elif action["action"] == "extract_single":
                try:
                    fields = action.get("fields", {}) or {}
                    symbol_selector = fields.get("symbol", "h1.apply-overflow-tooltip")
                    price_selector = fields.get("price", "span.js-symbol-last")

                    stock = scrape_single_stock(
                        driver,
                        symbol_selector=symbol_selector,
                        price_selector=price_selector
                    )

                    if stock and stock.get("symbol") and stock.get("price"):
                        response = {
                            "message": (
                                f"Stock Info:\n"
                                f"Symbol: {stock['symbol']}\n"
                                f"Price: {stock['price']}\n"
                                f"Performance: {json.dumps(stock['performance'], indent=2)}"
                                f"Key Stats: {'Available' if stock.get('key_stats_html') else 'Not found'}\n"
                                f"Chart: {'Attached' if stock.get('chart_image_base64') else 'Not found'}"
                            ),
                            "stocks": [stock],
                        }
                        logger.info(f"Returning single stock response: {json.dumps(response, indent=2)}")
                        return response
                    else:
                        return {"message": "No stock data found", "stocks": []}

                except Exception as e:
                    logger.error(f"Error extracting single stock: {str(e)}", exc_info=True)
                    return {"message": "Failed to extract single stock", "stocks": []}

    except TimeoutException as e:
        logger.error(f"Timeout scraping single stock data: {str(e)}")
        return {"message": f"Timeout scraping single stock data: {str(e)}", "stocks": []}

    except NoSuchElementException as e:
        logger.error(f"Element not found during single stock scraping: {str(e)}")
        return {"message": f"Element not found during single stock scraping: {str(e)}", "stocks": []}

    except Exception as e:
        logger.error(f"Single stock endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.warning(f"Failed to quit driver: {str(e)}")

@app.get("/stock_news")
async def fetch_stock_news(stock: str, url, count: int = 5, days_limit: int = 7):
    try:
        # Call scraping function
        driver = get_driver()
        news_list = scrape_stock_news(
            driver=driver,
            url=url,
            stock_ticker=stock,
            max_news=count,
            days_limit=days_limit
        )

        if not news_list:
            return {
                "actions": [],
                "message": f"Invalid stock ticker for news",
                "news": []
            }

        # Sort latest first
        news_list = sorted(
            news_list,
            key=lambda x: x.get("time") or "",
            reverse=True
        )

        return {
            "actions": [],
            "message": f"Latest {len(news_list)} news for {stock}",
            "news": news_list
        }

    except Exception as e:
        return {
            "actions": [],
            "message": "Error fetching news",
            "news": [],
            "error": str(e)
        }

@app.get("/sector_data")
async def fetch_sector_data(sector: str, count: int = 20):
    try:
        driver = get_driver()
        try:
            all_data = scrape_sector(sector, driver=driver, count=count)
            if not all_data or not any("Symbol" in record for record in all_data):
                logger.warning(f"Invalid or empty data for sector '{sector}': {all_data[:2]}")
                return {
                    "actions": [],
                    "message": f"No valid stock data found for sector '{sector}'",
                    "data": []
                }
            return {
                "actions": [],
                "message": f"Found {len(all_data)} stocks in {sector} sector",
                "data": all_data
            }
        finally:
            driver.quit()
    except Exception as e:
        logger.error(f"Error fetching sector '{sector}': {e}")
        return {
            "actions": [],
            "message": f"Error fetching sector data: {str(e)}",
            "data": [],
            "error": str(e)
        }

@app.get("/stock_chart")
async def get_stock_chart(ticker: str, timeframe: str = "12M"):
    try:
        result = display_stock_chart(ticker, timeframe, headless=False)
        return {
            "message": result["message"],
            "status": result["status"]
        }
    except Exception as e:
        logger.error(f"Error in stock_chart endpoint: {str(e)}")
        return {
            "message": f"Failed to display chart: {str(e)}",
            "status": "error"
        }