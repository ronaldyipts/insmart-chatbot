import json
from collections import deque
from urllib.parse import urljoin, urlparse

from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import os

# ============================================================
#  Application configuration
# ============================================================

app = Flask(__name__)

# 1. API key from environment variable
HKU_API_KEY = os.getenv("HKU_API_KEY")

# 2. Deployment name (must match HKU OpenAI deployment)
DEPLOYMENT_ID = "gpt-4.1-nano"  # TODO: set to actual deployment name

# 3. HKU OpenAI endpoint
API_VERSION = "2025-01-01-preview"
ENDPOINT = (
    f"https://api.hku.hk/openai/deployments/"
    f"{DEPLOYMENT_ID}/chat/completions?api-version={API_VERSION}"
)

# 4. IN‑SMART official homepage (crawler entry point)
INSMART_HOME = "https://insmart.cite.hku.hk/"

# Global state populated at startup
insmart_corpus = ""
crawler_error = None


# ============================================================
#  Utilities: fetch and clean HTML
# ============================================================

def fetch_html(url: str, timeout: int = 15) -> tuple[str, str]:
    """
    Send a GET request to the given URL and return:
      - response text
      - Content-Type header value
    """
    headers = {
      "User-Agent": "INSMART-QA-Bot/1.0 (+HKU)"
    }
    resp = requests.get(url, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp.text, resp.headers.get("Content-Type", "")


def html_to_text(html: str, max_chars: int = 5000) -> str:
    """
    Convert HTML to plain text:
      - remove script/style/noscript
      - strip each line and drop empty lines
      - truncate to max_chars
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = "\n".join(lines)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[content truncated]"

    return text


# ============================================================
#  Crawler: fetch up to 50 pages from the IN‑SMART site
# ============================================================

def crawl_insmart(
    start_url: str = INSMART_HOME,
    max_pages: int = 50,
    per_page_chars: int = 5000,
    total_chars: int = 30000,
) -> str:
    """
    Breadth‑first crawl starting from INSMART_HOME.

    Rules:
      - only follow links within the same domain
      - visit at most max_pages pages
      - extract at most per_page_chars characters per page
      - overall corpus is capped at total_chars characters
    """
    parsed = urlparse(start_url)
    base_domain = parsed.netloc
    base_scheme = parsed.scheme

    if base_scheme not in ("http", "https") or not base_domain:
        raise ValueError(f"Invalid start URL: {start_url}")

    visited: set[str] = set()
    queue: deque[str] = deque([start_url])
    collected: list[str] = []

    while queue and len(visited) < max_pages and len("".join(collected)) < total_chars:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            html, ctype = fetch_html(url)
        except Exception as e:
            collected.append(f"\n[Failed to fetch {url}: {e}]\n")
            continue

        # Non‑HTML content (e.g. PDF) – treat as plain text
        if "text/html" not in ctype:
            text = html
            if len(text) > per_page_chars:
                text = text[:per_page_chars] + "\n...[content truncated]"
            collected.append(f"\n[Content of {url}]\n{text}\n")
            continue

        # HTML → plain text
        page_text = html_to_text(html, max_chars=per_page_chars)
        collected.append(f"\n[Content of {url}]\n{page_text}\n")

        # Discover further links within the same domain (BFS)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full_url = urljoin(url, href)
            p = urlparse(full_url)

            if p.netloc == base_domain and p.scheme in ("http", "https"):
                if full_url not in visited:
                    queue.append(full_url)

        if len("".join(collected)) >= total_chars:
            break

    corpus = "".join(collected)
    if len(corpus) > total_chars:
        corpus = corpus[:total_chars] + "\n...[overall corpus truncated]"

    return corpus


def load_insmart_corpus() -> None:
    """
    Called once at app startup.

    Responsibilities:
      - run the crawler
      - populate global insmart_corpus
      - record any error message in crawler_error
    """
    global insmart_corpus, crawler_error
    try:
        print("[INSMART] Crawling up to 50 pages from:", INSMART_HOME)
        corpus = crawl_insmart(
            start_url=INSMART_HOME,
            max_pages=50,
            per_page_chars=5000,
            total_chars=30000,
        )
        insmart_corpus = corpus
        crawler_error = None
        print("[INSMART] Crawl finished. Length:", len(corpus))
    except Exception as e:
        crawler_error = str(e)
        insmart_corpus = ""
        print("[INSMART] Crawl failed:", e)


# ============================================================
#  Chat API: front‑end posts to /api/chat, back‑end calls HKU OpenAI
#  Now returns: reply + followups + history
# ============================================================

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    JSON API used by the front‑end chat UI.

    Request body:
        {
          "message": "<user message>",
          "history": [ ... optional previous messages ... ]
        }

    Response:
        {
          "reply": "<assistant reply>",
          "followups": ["...", "...", "..."],
          "history": [ ... updated history ... ]
        }
    """
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    history = data.get("history") or []

    if not user_message:
        return jsonify({"error": "message is required"}), 400

    # Build the system prompt: role description + crawled IN‑SMART content
    if crawler_error:
        crawl_note = f"[Note: error occurred while crawling IN-SMART at startup: {crawler_error}]"
    else:
        crawl_note = (
            "Below is content automatically retrieved at startup from the "
            "IN-SMART official website (up to 50 pages, Chinese and English, "
            "possibly truncated):"
        )

    # Chinese summary of IN‑SMART, based on the official site
    insmart_summary_zh = """
IN-SMART（「培育STEAM及人工智能人才的創新網絡計劃」）的支援目標包括：
1. 透過培育培訓團隊模式，並著重培育課程領導人才，提升學校課程領導能力和教師團隊專業水平；
2. 提升教師設計STEAM學習設計，以促進學生自主學習的能力，特別是將人工智能學習元素融入STEAM教學活動；
3. 制定培養教師人工智能素養的專業發展框架，並就提高教師人工智能素養和教學能力所需的有利學習條件和環境提出建議；
4. 提升教師通過STEAM教育，發展學生數碼素養的能力；
5. 發展學校設計和協調多層級連繫學習的能力，以促進學校的教育創新。

聯絡：
- 聯絡人：陳敏柔女士（計劃助理）
- 電話：3917 0744
- 電郵：yoyocmi@hku.hk
"""

    # System prompt that forces JSON (reply + followups) and language consistency
    system_prompt = f"""
You are the official Q&A assistant for the "IN-SMART – Innovative Network for STEAM and AI Talent"
project at The University of Hong Kong, serving mainly Hong Kong schools and teachers.

LANGUAGE:
- If the user's message is mainly in Chinese, respond in Traditional Chinese.
- If it is mainly in English, respond in English.
- If mixed, choose the dominant language but you may briefly use both when helpful.
- Whatever language you use in "reply", you MUST use the SAME language in ALL items of "followups".

ABOUT IN-SMART (EN SUMMARY):
- Chinese name: 「IN-SMART 培育STEAM及人工智能人才的創新網絡計劃」
- Main goals:
  1. Strengthen curriculum leadership and teachers’ professional capacity through a training‑team model;
  2. Enhance teachers’ ability to design STEAM learning tasks that foster students’ self-directed learning,
     especially integrating AI elements;
  3. Develop a professional development framework for teachers’ AI literacy and suggest enabling
     conditions and environments;
  4. Enhance teachers’ ability to develop students’ digital literacy through STEAM education;
  5. Support schools to design and coordinate multi-level connected learning to promote educational innovation.

ABOUT IN-SMART (ZH SUMMARY):
{insmart_summary_zh}

{crawl_note}

================ IN-SMART CRAWLED CONTENT (UP TO 50 PAGES) START ================
{insmart_corpus if insmart_corpus else "[No crawled content available at the moment]"}
================ IN-SMART CRAWLED CONTENT (UP TO 50 PAGES) END ==================

You must strictly follow these rules:

1. SCOPE
   - ONLY answer questions directly related to IN-SMART, its goals, activities, STEAM education,
     self-directed learning, AI in education, and closely related school implementation issues.
   - If the user asks something clearly unrelated (e.g. general news, entertainment, finance,
     personal matters), reply in the user's language that this chatbot only handles IN-SMART related
     enquiries and cannot answer that question.

2. CONTENT SOURCE
   - Base your answers primarily on the IN-SMART website content above.
   - If the user asks something NOT clearly covered, you may give general educational advice,
     BUT explicitly state that it is general advice and remind the user to check the latest
     official information on: {INSMART_HOME}
   - NEVER fabricate concrete factual details such as:
       * exact list of participating schools,
       * specific dates, quotas, or fees,
     unless they are clearly present in the crawled content.

3. STYLE
   - Be concise, structured and helpful; use bullet points when useful.
   - Do NOT use Markdown formatting in your reply text. Plain text is enough.

4. OUTPUT FORMAT (IMPORTANT)
   - You must output ONLY valid JSON in the following format, with double quotes and no extra text:

   {{
     "reply": "your main answer to the user, in the appropriate language",
     "followups": [
       "follow-up question 1, SAME LANGUAGE as reply",
       "follow-up question 2, SAME LANGUAGE as reply",
       "follow-up question 3, SAME LANGUAGE as reply"
     ]
   }}

   - Do not include any explanation outside this JSON.
   - "followups" must be tailored to THIS conversation turn:
       * closely related to the user's question AND your reply
       * help the user go deeper into IN-SMART, e.g.:
         - ask more about support focus, activities, or participation modes,
         - ask about practical implementation of STEAM/AI/self-directed learning in school,
         - ask how IN-SMART can support their specific role (e.g. subject panel head, teacher, school leader).
   - If the user's message is in Traditional Chinese, both "reply" and all "followups" MUST be in Traditional Chinese.
   - If the user's message is in English, both "reply" and all "followups" MUST be in English.
"""

    messages = [{"role": "system", "content": system_prompt}]

    if isinstance(history, list):
        messages.extend(history)

    messages.append({"role": "user", "content": user_message})

    headers = {
        "Content-Type": "application/json",
        "api-key": HKU_API_KEY,
    }

    body = {
        "messages": messages,
        "model": DEPLOYMENT_ID,
        "temperature": 0.5,   # slightly higher for more varied followups
        "max_tokens": 800,
    }

    try:
        resp = requests.post(ENDPOINT, headers=headers, data=json.dumps(body))
    except Exception as e:
        return jsonify({"error": f"request failed: {e}"}), 500

    if resp.status_code != 200:
        # You can refine 429 handling here if needed
        return jsonify({
            "error": "upstream_error",
            "status": resp.status_code,
            "body": resp.text
        }), resp.status_code

    data_resp = resp.json()
    raw_content = data_resp["choices"][0]["message"]["content"]

    # ============================================================
    #  Parse model JSON output robustly: reply + followups
    # ============================================================

    reply_text: str = ""
    followups: list[str] = []

    parsed = None

    # 1) First try direct JSON parse
    try:
        parsed = json.loads(raw_content)
    except Exception:
        # 2) If that fails, try to extract the first {...} block and parse
        start = raw_content.find("{")
        end = raw_content.rfind("}")
        if start != -1 and end != -1 and end > start:
            maybe_json = raw_content[start:end + 1]
            try:
                parsed = json.loads(maybe_json)
            except Exception:
                parsed = None

    if isinstance(parsed, dict):
        if isinstance(parsed.get("reply"), str):
            reply_text = parsed["reply"]
        if isinstance(parsed.get("followups"), list):
            followups = [f for f in parsed["followups"] if isinstance(f, str)]

    # 3) If still no reply_text, fall back to using the raw content
    if not reply_text:
        reply_text = raw_content

    # 4) If followups are empty, create a language‑aware fallback set,
    #    written from the USER's "I" perspective (so each button looks like
    #    a natural question the user might ask next).
    if not followups:
        import re
        has_cjk = re.search(r"[\u4e00-\u9fff]", reply_text) is not None

        if has_cjk:
            # Traditional Chinese, user-perspective questions
            followups = [
                "我還可以進一步了解哪些有關 IN-SMART 支援目標或活動的資訊？",
                "我可以如何善用 IN-SMART 提供的教師培訓或 STEAM／AI 教學設計支援？",
                "如果我之後有問題或想參加計劃，我可以用甚麼方式聯絡 IN-SMART 團隊？"
            ]
        else:
            # English, user-perspective questions
            followups = [
                "What else can I learn about IN-SMART’s support goals or activities?",
                "How can I make use of IN-SMART’s support for teacher training or STEAM/AI learning design?",
                "If I have more questions or want to participate, how can I contact the IN-SMART team?"
            ]

    # ============================================================
    #  Update history and return to front‑end
    # ============================================================

    if not isinstance(history, list):
        history = []
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply_text})

    response_payload = {
        "reply": reply_text,
        "followups": followups,
        "history": history,
    }

    return jsonify(response_payload)


# ============================================================
#  Routes
# ============================================================

@app.route("/")
def index():
    # Render templates/index.html
    return render_template("index.html")


if __name__ == "__main__":
    # Pre‑load IN‑SMART website content at startup for later Q&A
    load_insmart_corpus()
    app.run(host="0.0.0.0", port=5000, debug=True)