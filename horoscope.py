import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
import urllib3
# 導入 Google 官方最新 GenAI 套件
from google import genai

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

# 🪐 初始化 Gemini 客戶端
# 它會自動去抓取系統環境變數中的 GEMINI_API_KEY
client = genai.Client()

def ask_gemini_to_shorten(sign_name, long_text):
    # 🌟 修改提示詞：明確指定 80~120 字的區間，並要求提供具體運勢分析
    prompt = (
        f"你是一個說話帶點實況梗、幽默且一針見血的圖奇聊天室占卜大師。\n"
        f"請幫我把以下【{sign_name}】的今日運勢，精簡成一段「適合聊天室閱讀、大約 100 字上下」的精闢短評。\n"
        f"內容必須包含整體的運勢亮點或該注意的雷區（例如工作、感情或財運），語氣可以調侃，但字數嚴格控制在 80 到 120 字之間，不要分行：\n\n"
        f"{long_text}"
    )
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        # 防禦機制：若 AI 出錯，放寬切片長度到 100 字
        return long_text[:100] + "..."

def get_today_horoscope(sign_name):
    sign_map = {
        "牡羊座": 0, "金牛座": 1, "雙子座": 2, "巨蟹座": 3,
        "獅子座": 4, "處女座": 5, "天秤座": 6, "天蠍座": 7,
        "射手座": 8, "摩羯座": 9, "水瓶座": 10, "雙魚座": 11
    }
    if sign_name not in sign_map:
        return "🔮 請輸入正確的星座名稱（例如：!星座 雙子座）"
        
    sign_id = sign_map[sign_name]
    url = f"https://astro.click108.com.tw/daily_{sign_id}.php?iAstro={sign_id}"
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, verify=False)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        content_tag = soup.find(class_="TODAY_CONTENT")
        
        if content_tag:
            clean_text = content_tag.text.replace("\n", " ").strip()
            
            # ⭐【最大大腦升級】：把原本抓下來的長文，丟給 Gemini 濃縮！
            short_luck_text = ask_gemini_to_shorten(sign_name, clean_text)
            
            return f"【{sign_name}今日運勢】{short_luck_text}"
        else:
            return f"❌ 暫時無法解析 {sign_name} 的運勢網頁。"
    except Exception as e:
        return f"💥 伺服器連線異常: {str(e)}"

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
        
    # 確保抓到星座資料
    raw_fortune = get_today_horoscope(sign)
    
    # 防呆：如果原本就回傳錯誤訊息（例如"請輸入正確星座"），直接吐出，不浪費 API KEY
    if "❌" in raw_fortune or "🔮" in raw_fortune or "💥" in raw_fortune:
        return raw_fortune
        
    # 強制在這裡送進 Gemini AI 進行 100 字濃縮
    try:
        short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
        return f"【{sign}今日運勢】{short_fortune}"
    except Exception as e:
        # 如果 AI 真的萬一掛掉，才降級回傳原始文字的前 100 字
        return f"【{sign}今日運勢】(AI維護中) {raw_fortune[:100]}..."

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)