const LLM_ACTION_API = "http://localhost:8000/llm_refine";

// Get DOM elements
const chatContainer = document.getElementById("chat-container");
const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("message");
const sendBtn = document.getElementById("send-btn");
const loadingDiv = document.getElementById("loading");
const closeBtn = document.getElementById("chat-close");

// Validate DOM elements
if (!chatContainer || !chatBox || !userInput || !sendBtn || !loadingDiv || !closeBtn) {
    console.error("Required DOM elements are missing");
    throw new Error("Required DOM elements are missing");
}

// Close chat only when the close button is clicked
closeBtn.addEventListener("click", () => {
    chatContainer.remove();
});

async function sendMessage() {
    const message = userInput.value.trim();
    if (!message) return;

    addMessage(message, "user");
    userInput.value = "";
    loadingDiv.style.display = "block";

    try {
        const response = await fetch(LLM_ACTION_API, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: message })
        });

        if (!response.ok) {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        console.log('API Response:', data);

        // Validate response structure
        if (!data || typeof data !== 'object') {
            throw new Error("Invalid API response format");
        }

        // Use refined_message or message, fallback to default
        let displayMessage = data.refined_message || data.message || "No response received";
        let chartBase64 = null;

        // Safely access stocks and chart_image_base64
        if (Array.isArray(data.stocks) && data.stocks.length > 0 && data.stocks[0].chart_image_base64){
            chartBase64 = data.stocks[0].chart_image_base64;
            // Basic validation for base64 (check PNG header)
            if (!chartBase64.startsWith('iVBORw0KGgo')) {
                console.warn('Invalid base64 image data');
                chartBase64 = null;
                displayMessage += "\nChart: Invalid image data";
            }
        }

        addMessage(displayMessage, "bot", chartBase64);

    } catch (err) {
        console.error('Fetch error:', err);
        addMessage(`Error: ${err.message}`, "bot");
    } finally {
        loadingDiv.style.display = "none";
    }
}

// The addMessage function to display text and image in the chat
function addMessage(text, type, chartBase64 = null) {
    const chatBox = document.getElementById("chat-box");
    const msgDiv = document.createElement("div");
    msgDiv.classList.add("message", type === "user" ? "user-message" : "bot-message");
    msgDiv.style.whiteSpace = "pre-line";

    // Add text
    msgDiv.innerText = text;

    // If base64 chart data is provided, show it as an image
    if (chartBase64) {
        const img = document.createElement("img");
        img.src = `data:image/png;base64,${chartBase64}`;
        img.style.maxWidth = "100%";
        img.style.marginTop = "8px";
        // Handle image load errors
        img.onerror = () => {
            console.warn("Failed to load chart image");
            msgDiv.innerText += "\nChart: Failed to load image";
            img.remove(); // Remove broken image
        };
        msgDiv.appendChild(img);
    }

    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Bind send events
sendBtn.addEventListener("click", sendMessage);
userInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendMessage();
});