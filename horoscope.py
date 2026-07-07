import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI

# 建立一個 FastAPI 應用程式物件（這就是你的網頁外殼）
app = FastAPI()

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
        response = requests.get(url, headers=headers)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        content_tag = soup.find(class_="TODAY_CONTENT")
        
        if content_tag:
            luck_text = content_tag.text.strip()[:80] + "..."
            return f"🌌【{sign_name}今日運勢】{luck_text}"
        else:
            return f"❌ 暫時無法解析 {sign_name} 的運勢網頁。"
    except Exception as e:
        return f"💥 伺服器連線異常: {str(e)}"

# 🪐 這裡設定網頁路由：當有人連到 /horoscope 時觸發
@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    # sign 就是網址後面的參數，例如 ?sign=雙子座
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
    
    # 呼叫上面的爬蟲函式，並直接回傳文字給網頁
    return get_today_horoscope(sign)

# 啟動網頁伺服器
if __name__ == "__main__":
    import uvicorn
    # 讓伺服器跑在本地端的 8000 連接埠
    uvicorn.run(app, host="127.0.0.1", port=8000)