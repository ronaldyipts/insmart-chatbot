from flask import Flask, request, jsonify, render_template
import os
import json
import requests
import re

app = Flask(__name__, template_folder="../templates")

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

insmart_corpus = INSMART_SUMMARY_ZH + "\n\n" + INSMART_SUMMARY_EN


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    history = data.get("history") or []

    if not user_message:
        return jsonify({"error": "message is required"}), 400

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
{INSMART_SUMMARY_ZH}

Below is a consolidated text summary derived from the official homepage {INSMART_HOME}.
You may treat it as part of the authoritative project description:

================ IN-SMART CONSOLIDATED CONTENT START ================
{insmart_corpus}
================ IN-SMART CONSOLIDATED CONTENT END ==================

You must strictly follow these rules:

1. SCOPE
   - ONLY answer questions directly related to IN-SMART, its goals, activities, STEAM education,
     self-directed learning, AI in education, and closely related school implementation issues.
   - If the user asks something clearly unrelated, reply in the user's language that this chatbot
     only handles IN-SMART related enquiries and cannot answer that question.

2. CONTENT SOURCE
   - Base your answers primarily on the IN-SMART information above.
   - If the user asks something NOT clearly covered, you may give general educational advice,
     BUT explicitly state that it is general advice and remind the user to check the latest
     official information on: {INSMART_HOME}
   - NEVER fabricate concrete factual details such as exact lists of participating schools
     or specific dates, quotas, or fees.

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
   - "followups" must be tailored to THIS conversation turn.
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

    reply_text = ""
    followups = []

    try:
        parsed = json.loads(raw_content)
    except Exception:
        start = raw_content.find("{")
        end = raw_content.rfind("}")
        parsed = None
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

    if not reply_text:
        reply_text = raw_content

    if not followups:
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

    if not isinstance(history, list):
        history = []
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply_text})

    return jsonify({
        "reply": reply_text,
        "followups": followups,
        "history": history,
    })


# Vercel 會自動偵測到這個 app 物件
# 不需要 if __name__ == "__main__" 區塊