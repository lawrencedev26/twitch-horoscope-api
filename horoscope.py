import os
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from fastapi import FastAPI, BackgroundTasks
import urllib3
from google import genai
from datetime import datetime, timezone, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

# 🚀 程式啟動時，自動檢查並建立資料庫表格
@app.on_event("startup")
def startup_db_client():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("⚠️ 警告：未設定 DATABASE_URL 環境變數")
        return
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        # 建立表格，增加 target_date 欄位來確保我們抓到的是「今天」的運勢
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS horoscope (
            sign VARCHAR(10) PRIMARY KEY,
            fortune_text TEXT NOT NULL,
            target_date VARCHAR(10) NOT NULL
        );
        """)
        conn.commit()
        print("✓ PostgreSQL 資料庫初始化成功！")
    except Exception as e:
        print(f"❌ 初始化資料庫失敗: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

# 🗄️ 新增：把資料寫入 PostgreSQL
def save_fortune_to_db(sign, text, target_date):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url: return
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        query = """
        INSERT INTO horoscope (sign, fortune_text, target_date)
        VALUES (%s, %s, %s)
        ON CONFLICT (sign) 
        DO UPDATE SET fortune_text = EXCLUDED.fortune_text, target_date = EXCLUDED.target_date;
        """
        cursor.execute(query, (sign, text, target_date))
        conn.commit()
    except Exception as e:
        print(f"DB寫入失敗: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

# 🗄️ 新增：從 PostgreSQL 讀取資料
def get_fortune_from_db(sign, target_date):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url: return None
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        # 必須是指定的星座，而且日期必須是「今天」
        query = "SELECT fortune_text FROM horoscope WHERE sign = %s AND target_date = %s;"
        cursor.execute(query, (sign, target_date))
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        print(f"DB讀取失敗: {e}")
        return None
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

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
            model='gemini-3.5-flash',
            contents=prompt,
        )
        ai_reply = response.text.strip()
        
        if len(ai_reply) > 250:
            return ai_reply[:240] + "..."
            
        return ai_reply
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 100:
            error_msg = error_msg[:100] + "..."
        return f"【AI 呼叫失敗】：{error_msg}"

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

# 🌟 自動更新腳本（寫入資料庫）
def auto_fetch_all_signs():
    signs = [
        "牡羊座", "金牛座", "雙子座", "巨蟹座",
        "獅子座", "處女座", "天秤座", "天蠍座",
        "射手座", "摩羯座", "水瓶座", "雙魚座"
    ]
    today_date = get_tw_today()
    
    for sign in signs:
        raw_fortune = get_today_horoscope(sign)
        
        if raw_fortune not in ["ERROR_SIGN", "ERROR_PARSE", "ERROR_CONN"]:
            short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
            final_result = f"🔮【{sign}今日運勢】{short_fortune}"
            
            # 只有在 AI 呼叫成功時，才存入資料庫
            if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
                save_fortune_to_db(sign, final_result, today_date)
                
        # 停頓 5 秒保護額度
        time.sleep(5)

@app.get("/warmup")
def warmup_cache(background_tasks: BackgroundTasks):
    background_tasks.add_task(auto_fetch_all_signs)
    return {"status": "開始在背景自動抓取 12 星座運勢，並存入雲端資料庫！大約需時 60 秒。"}

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
        
    today_date = get_tw_today()
    
    # 🎯 優先去資料庫找今天的運勢 (0.01秒超高速)
    db_fortune = get_fortune_from_db(sign, today_date)
    if db_fortune:
        return db_fortune
        
    # 如果資料庫沒有（例如第一天剛開機，或半夜鬧鐘還沒響），才即時抓取
    raw_fortune = get_today_horoscope(sign)
    if raw_fortune == "ERROR_SIGN":
        return "🔮 請輸入正確的星座名稱（例如：!星座 雙子座）"
    elif raw_fortune == "ERROR_PARSE":
        return f"❌ 暫時無法解析 {sign} 的運勢網頁。"
    elif raw_fortune == "ERROR_CONN":
        return "💥 伺服器連線異常，請稍後再試。"
        
    short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
    final_result = f"🔮【{sign}今日運勢】{short_fortune}"
    
    # 抓取成功後，順手存進資料庫
    if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
        save_fortune_to_db(sign, final_result, today_date)
        
    return final_result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
