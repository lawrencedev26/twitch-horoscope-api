import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
import urllib3
from google import genai

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

def ask_gemini_to_shorten(sign_name, long_text):
    prompt = (
        f"你現在是 Twitch 實況聊天室的占卜大師，說話幽默、一針見血、帶點實況梗。\n\n"
        f"【絕對命令】：請將下方提供的星座運勢原創長文，徹底改寫並濃縮成『一段 100 字左右』的精闢短評。\n"
        f"【規則要求】：\n"
        f"1. 必須包含運勢核心重點或該注意的雷區。\n"
        f"2. 語氣可以調侃，字數嚴格限制在 80 到 120 字之間，絕對不要有換行符號。\n"
        f"3. 絕對、千萬、嚴禁直接複製或照抄原本的長文！必須用你自己的口吻改寫！\n\n"
        f"【以下是需要你改寫濃縮的運勢長文】：\n"
        f"{long_text}"
    )
    try:
        # 🌟 修正：把 Client 的建立搬進 try 裡面，並強制檢查 Key
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "【錯誤診斷】Render 後台找不到 GEMINI_API_KEY 環境變數，請檢查 Environment 設定。"
            
        client = genai.Client(api_key=api_key)
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        ai_reply = response.text.strip()
        
        if len(ai_reply) > 150:
            return ai_reply[:100] + "..."
            
        return ai_reply
    except Exception as e:
        # 🌟 修正：萬一失敗，直接把錯誤訊息（e）噴出來，讓我們知道為什麼失敗
        return f"【AI 呼叫失敗原因】：{str(e)}"

def get_today_horoscope(sign_name):
    sign_map = {
        "牡羊座": 0, "金牛座": 1, "雙子座": 2, "巨蟹座": 3,
        "獅子座": 4, "處女座": 5, "天秤座": 6, "天蠍座": 7,
        "射手座": 8, "摩羯座": 9, "水瓶座": 10, "雙魚座": 11
    }
    if sign_name not in sign_map:
        return "ERROR_SIGN"
        
    sign_id = sign_map[sign_name]
    url = f"https://astro.click108.com.tw/daily_{sign_id}.php?iAstro={sign_id}"
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, verify=False)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        content_tag = soup.find(class_="TODAY_CONTENT")
        
        if content_tag:
            return content_tag.text.replace("\n", " ").strip()
        else:
            return "ERROR_PARSE"
    except Exception as e:
        return "ERROR_CONN"

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
        
    raw_fortune = get_today_horoscope(sign)
    
    if raw_fortune == "ERROR_SIGN":
        return "🔮 請輸入正確的星座名稱（例如：!星座 雙子座）"
    elif raw_fortune == "ERROR_PARSE":
        return f"❌ 暫時無法解析 {sign} 的運勢網頁。"
    elif raw_fortune == "ERROR_CONN":
        return "💥 伺服器連線異常，請稍後再試。"
        
    short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
    
    return f"【{sign}今日運勢】{short_fortune}"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)