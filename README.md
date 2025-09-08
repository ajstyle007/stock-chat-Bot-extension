# 📊 Stock ChatBot Extension

A Chrome extension powered by Selenium, FastAPI, and LangChain that lets you interact with the stock market through a chat interface.

<img width="1169" height="836" alt="Screenshot 2025-09-08 131610" src="https://github.com/user-attachments/assets/03ba5aa8-33ab-48f1-ba75-60fa3a61cf19" />


Get insights like:

✅ Best & worst performing stocks
✅ Info about a single stock
✅ Latest stock news
✅ Charts of specific stocks (1D, 1Y, 5Y, etc.)
✅ Sector-wise stock performance

All packed into a neat browser extension!

### ⚡ Features

- AI-driven chat → Ask natural language queries like “Show me the top 10 performing stocks today”.
- Web scraping with Selenium → Real-time stock and sector data.
- FastAPI backend → Manages communication between the extension and scraping logic.
- LangChain integration → Converts user queries into structured actions.
- Chrome Extension frontend → Simple HTML/CSS/JS UI for chatting.

### 🛠️ Tech Stack

- Frontend: HTML, CSS, JavaScript (Chrome Extension)
- Backend: FastAPI
- Scraping: Selenium
- LLM Orchestration: LangChain
- Language: Python

### 📂 Project Structure

```
📦 stock-chat-Bot-extension
├── app.py
├── sel.py # Selenium stock scraping
├── popup.html
├── popup.js
├── popup.css
└── manifest.json
├── requirements.txt

```

### 🚀 Getting Started

#### 1️⃣ Clone the repo
```

git clone https://github.com/ajstyle007/stock-chat-Bot-extension.git
cd stock-chat-Bot-extension

```

#### 2️⃣ Install dependencies
```
pip install -r requirements.txt
```

#### 3️⃣ Run FastAPI backend
```
uvicorn app:app --reload
```

#### 4️⃣ Load the extension in Chrome

1. Open chrome://extensions/
2. Enable Developer mode
3. Click Load unpacked
4. Select the extension/ folder

#### 💡 Example Query

👉 User: “Show me top 10 today’s best performing stocks”
👉 Extension: Displays a table of top 10 stocks with price, % change, and volume.

#### ⚔️ Challenges Faced

- Prompt engineering for LLM query → mapping to correct stock/sector actions.
- Integrating frontend JS with FastAPI backend.
- Extracting the right HTML tags for stock tables & charts.
- Handling dynamic data loading in Selenium.

#### 🔮 Future Improvements

- Replace Selenium with faster APIs (if available).
- Add authentication & user preferences.
- Improve LLM with function calling for structured queries.
- Show interactive charts directly in the extension popup.

#### 🤝 Contributing

Contributions are welcome! Feel free to fork the repo and submit a PR 🚀

#### 📜 License
MIT License
