# api/chat.py
from app import app as flask_app

# Vercel Python serverless function entrypoint
def handler(event, context):
    # Vercel 會把 HTTP 請求映射到這個 handler，我們只要
    # 把它轉給 Flask WSGI app 處理即可。
    from werkzeug.wrappers import Response
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from werkzeug.test import EnvironBuilder

    path = event.get("path", "/api/chat")
    method = event.get("httpMethod", "POST")
    headers = event.get("headers") or {}
    body = event.get("body") or ""

    # 建立 WSGI 環境
    builder = EnvironBuilder(
        path=path,
        method=method,
        headers=headers,
        data=body,
    )
    env = builder.get_environ()

    # 呼叫 Flask app
    response: Response = Response.from_app(flask_app, env)

    return {
        "statusCode": response.status_code,
        "headers": dict(response.headers),
        "body": response.get_data(as_text=True),
    }