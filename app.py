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

# 4. IN‑SMART official homepage (for reference only)
INSMART_HOME = "https://insmart.cite.hku.hk/"

# ============================================================
#  固定版 IN‑SMART 官網摘要（以你給的主頁內容整理）
# ============================================================

INSMART_SUMMARY_ZH = """
IN-SMART（「培育STEAM及人工智能人才的創新網絡計劃」）的主要支援目標包括：
1. 透過培育「培訓團隊模式」，並著重培育課程領導人才，提升學校課程領導能力和教師團隊專業水平；
2. 提升教師設計 STEAM 學習設計的能力，以促進學生自主學習，特別是把人工智能學習元素融入 STEAM 教學活動；
3. 制定培養教師人工智能素養的專業發展框架，並就提升教師人工智能素養和教學能力所需的有利學習條件和環境提出建議；
4. 提升教師透過 STEAM 教育發展學生數碼素養的能力；
5. 發展學校設計和協調多層級連繫學習的能力，以促進學校的教育創新。

網站亦提供：
- 「支援重點」、「支援活動及模式」、「概念框架」、「項目框架」及「自主學習」、「STEAM 教育」、「SDL-STEAM 的學習設計」等內容；
- 2025-26 參與學校名單；
- 會議、工作坊及培訓班等活動資訊；
- 相關資源及同意通知書（2025-2026 學年）等文件。

聯絡資料：
- 聯絡人：陳敏柔女士（計劃助理）
- 電話：3917 0744
- 電郵：yoyocmi@hku.hk

研究操守：
- 本計劃獲香港大學非臨床研究操守委員會批准，參考編號：EA250499。
"""

INSMART_SUMMARY_EN = """
IN-SMART (Innovative Network for STEAM and AI Talent) is a support project hosted by
The University of Hong Kong. Based on the official website, the key support goals are:

1. To strengthen schools’ curriculum leadership capacity and teachers’ professional competence
   through a training-team model that emphasises curriculum leaders;
2. To enhance teachers’ ability to design STEAM learning activities that foster students’
   self-directed learning, especially by integrating AI learning elements into STEAM teaching;
3. To develop a professional development framework for teachers’ AI literacy and to propose
   enabling conditions and environments for enhancing teachers’ AI literacy and teaching capacity;
4. To enhance teachers’ capability to develop students’ digital literacy through STEAM education;
5. To develop schools’ capacity to design and coordinate multi-level, connected learning in order
   to promote educational innovation.

The website also provides:
- Key support foci, support activities and modes, conceptual and project frameworks;
- Information about self-directed learning, STEAM education, and SDL–STEAM learning design;
- A list of participating schools (e.g., for 2025–26);
- Information about conferences, workshops and training courses;
- Resources and the consent form for the 2025–2026 school year.

Contact:
- Contact person: Ms. Chan Man Yau (Project Assistant)
- Tel: (+852) 3917 0744
- Email: yoyocmi@hku.hk

Research ethics:
- The project has been approved by the HKU non-clinical research ethics committee,
  reference number EA250499.
"""

# 若將來真的需要 crawler，可再開啟；目前為了部署穩定先停用。
insmart_corpus = INSMART_SUMMARY_ZH + "\n\n" + INSMART_SUMMARY_EN
crawler_error = None


# ============================================================
#  Chat API: front‑end posts to /api/chat, back‑end calls HKU OpenAI
#  Returns: reply + followups + history
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

    # Chinese summary of IN‑SMART, based on the official site
    insmart_summary_zh = INSMART_SUMMARY_ZH

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
{INSMART_SUMMARY_EN}

ABOUT IN-SMART (ZH SUMMARY):
{insmart_summary_zh}

Below is a consolidated text summary derived from the official homepage {INSMART_HOME}.
You may treat it as part of the authoritative project description:

================ IN-SMART CONSOLIDATED CONTENT START ================
{insmart_corpus}
================ IN-SMART CONSOLIDATED CONTENT END ==================

You must strictly follow these rules:

1. SCOPE
   - ONLY answer questions directly related to IN-SMART, its goals, activities, STEAM education,
     self-directed learning, AI in education, and closely related school implementation issues.
   - If the user asks something clearly unrelated (e.g. general news, entertainment, finance,
     personal matters), reply in the user's language that this chatbot only handles IN-SMART related
     enquiries and cannot answer that question.

2. CONTENT SOURCE
   - Base your answers primarily on the IN-SMART information above.
   - If the user asks something NOT clearly covered, you may give general educational advice,
     BUT explicitly state that it is general advice and remind the user to check the latest
     official information on: {INSMART_HOME}
   - NEVER fabricate concrete factual details such as:
       * exact list of participating schools,
       * specific dates, quotas, or fees,
     unless they are clearly present in the provided content.

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
        "temperature": 0.5,
        "max_tokens": 800,
    }

    try:
        resp = requests.post(ENDPOINT, headers=headers, data=json.dumps(body))
    except Exception as e:
        return jsonify({"error": f"request failed: {e}"}), 500

    if resp.status_code != 200:
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

    # 4) If followups are empty, create a language‑aware fallback set
    if not followups:
        import re
        has_cjk = re.search(r"[\u4e00-\u9fff]", reply_text) is not None

        if has_cjk:
            followups = [
                "我還可以進一步了解哪些有關 IN-SMART 支援目標或活動的資訊？",
                "我可以如何善用 IN-SMART 提供的教師培訓或 STEAM／AI 教學設計支援？",
                "如果我之後有問題或想參加計劃，我可以用甚麼方式聯絡 IN-SMART 團隊？"
            ]
        else:
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
    # 不再啟動 crawler，啟動時只用固定摘要即可
    app.run(host="0.0.0.0", port=5000, debug=True)