import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
import urllib3
from google import genai

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()
client = genai.Client()

def ask_gemini_to_shorten(sign_name, long_text):
    prompt = (
        f"你是一個說話帶點實況梗、幽默且一針見血的圖奇聊天室占卜大師。\n"
        f"請幫我把以下【{sign_name}】的今日運勢，精簡成一段「適合聊天室閱讀、大約 100 字上下」的精闢短評。\n"
        f"內容必須包含整體的運勢亮點或該注意的雷區（例如工作、感情或財運），語氣可以調侃，但字數嚴格控制在 80 到 120 字之間，絕對不要換行：\n\n"
        f"{long_text}"
    )
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        return long_text[:100] + "..."

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
            # ⭐【只回傳純文字】：不做多餘的包裝，把最乾淨的原創長文丟回去
            return content_tag.text.replace("\n", " ").strip()
        else:
            return "ERROR_PARSE"
    except Exception as e:
        return "ERROR_CONN"

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
        
    # 1. 去網站撈取最原始的長文
    raw_fortune = get_today_horoscope(sign)
    
    # 2. 判斷爬蟲是否異常
    if raw_fortune == "ERROR_SIGN":
        return "🔮 請輸入正確的星座名稱（例如：!星座 雙子座）"
    elif raw_fortune == "ERROR_PARSE":
        return f"❌ 暫時無法解析 {sign} 的運勢網頁。"
    elif raw_fortune == "ERROR_CONN":
        return "💥 伺服器連線異常，請稍後再試。"
        
    # 3. 確保只在這裡呼叫「唯一一次」Gemini AI 進行 100 字濃縮
    short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
    
    # 4. 輸出最終有條理的成品
    return f"【{sign}今日運勢】{short_fortune}"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)