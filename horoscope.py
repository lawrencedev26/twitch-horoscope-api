import os
import time
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, BackgroundTasks
import urllib3
from google import genai
from datetime import datetime, timezone, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()
fortune_cache = {}

def get_tw_today():
    tw_tz = timezone(timedelta(hours=8))
    return datetime.now(tw_tz).strftime("%Y-%m-%d")

def ask_gemini_to_shorten(sign_name, long_text):
    prompt = (
        f"你現在一位女性占卜師，感覺嚴肅且溫柔，還有修習過心理學碩士，非常體貼的占卜師。\n\n"
        f"【絕對命令】：請將下方運勢長文濃縮成『大約 120 到 140 字左右』的精闢短評。\n"
        f"【規則要求】：\n"
        f"1. 必須包含運勢核心重點。\n"
        f"2. 語氣調侃，絕對不要有換行符號。\n"
        f"3. 嚴禁直接照抄原文！\n"
        f"4. 請確保最後一句話有完整說完，並且務必以全形句號「。」作結尾！\n\n"
        f"【運勢長文】：\n"
        f"{long_text}"
    )
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "【錯誤診斷】Render 後台找不到 GEMINI_API_KEY。"
            
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        ai_reply = response.text.strip()
        
        if len(ai_reply) > 200:
            return ai_reply[:200] + "..."
        return ai_reply
    except Exception as e:
        return f"【AI 呼叫失敗】：{str(e)}"

def get_today_horoscope(sign_name):
    sign_map = {
        "牡羊座": 0, "金牛座": 1, "雙子座": 2, "巨蟹座": 3,
        "獅子座": 4, "處女座": 5, "天秤座": 6, "天蠍座": 7,
        "射手座": 8, "摩羯座": 9, "水瓶座": 10, "雙魚座": 11
    }
    sign_id = sign_map.get(sign_name)
    if sign_id is None:
        return "ERROR_SIGN"
        
    url = f"https://astro.click108.com.tw/daily_{sign_id}.php?iAstro={sign_id}"
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, verify=False, timeout=5)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        content_tag = soup.find(class_="TODAY_CONTENT")
        
        if content_tag:
            return content_tag.text.replace("\n", " ").strip()
        else:
            return "ERROR_PARSE"
    except Exception as e:
        return "ERROR_CONN"

# 🌟 新增的自動更新腳本
def auto_fetch_all_signs():
    signs = [
        "牡羊座", "金牛座", "雙子座", "巨蟹座",
        "獅子座", "處女座", "天秤座", "天蠍座",
        "射手座", "摩羯座", "水瓶座", "雙魚座"
    ]
    today_date = get_tw_today()
    
    for sign in signs:
        cache_key = f"{today_date}_{sign}"
        raw_fortune = get_today_horoscope(sign)
        
        if raw_fortune not in ["ERROR_SIGN", "ERROR_PARSE", "ERROR_CONN"]:
            short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
            final_result = f"🔮【{sign}今日運勢】{short_fortune}"
            
            if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
                fortune_cache[cache_key] = final_result
                
        # 停頓 2 秒，避免瞬間呼叫 12 次 AI 觸發 Google 免費額度的速率限制
        time.sleep(2)

# 🌟 新增的專屬後門：用來觸發背景更新
@app.get("/warmup")
def warmup_cache(background_tasks: BackgroundTasks):
    # 讓程式在背景去跑 auto_fetch_all_signs，網頁則立刻回傳成功，不讓呼叫端乾等
    background_tasks.add_task(auto_fetch_all_signs)
    return {"status": "開始在背景自動抓取 12 星座運勢！大約需時 30 秒。"}

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
        
    today_date = get_tw_today()
    cache_key = f"{today_date}_{sign}"
    
    # 百寶箱命中，0.01 秒回傳
    if cache_key in fortune_cache:
        return fortune_cache[cache_key]
        
    # 如果百寶箱沒有（例如鬧鐘還沒響就有人查），才即時查
    raw_fortune = get_today_horoscope(sign)
    if raw_fortune == "ERROR_SIGN":
        return "🔮 請輸入正確的星座名稱（例如：!星座 雙子座）"
    elif raw_fortune == "ERROR_PARSE":
        return f"❌ 暫時無法解析 {sign} 的運勢網頁。"
    elif raw_fortune == "ERROR_CONN":
        return "💥 伺服器連線異常，請稍後再試。"
        
    short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
    final_result = f"🔮【{sign}今日運勢】{short_fortune}"
    
    if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
        fortune_cache[cache_key] = final_result
        
    return final_result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)