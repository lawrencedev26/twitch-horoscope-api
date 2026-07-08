import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
# 導入這行用來關閉因為跳過安全檢查而跳出的滿大堆警告訊息
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        
        # ⭐【關鍵修正】：在這裡加上 verify=False，強行跳過 SSL 憑證檢查
        response = requests.get(url, headers=headers, verify=False)
        
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        content_tag = soup.find(class_="TODAY_CONTENT")
        
        if content_tag:
            # 1. 取得網頁文字，並把裡面的換行符號 (\n) 全部換成空白
            clean_text = content_tag.text.replace("\n", " ").strip()
            
            # 2. 放寬字數到 150 個字，讓敘述更完整
            luck_text = clean_text[:150] + "..."
            return f"🌌【{sign_name}今日運勢】{luck_text}"
        else:
            return f"❌ 暫時無法解析 {sign_name} 的運勢網頁。"
    except Exception as e:
        return f"💥 伺服器連線異常: {str(e)}"

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
    return get_today_horoscope(sign)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)