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

# 🗄️ 把資料寫入 PostgreSQL
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
        print(f"✓ [{sign}] 成功寫入資料庫！")
    except Exception as e:
        print(f"❌ [{sign}] DB寫入失敗: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

# 🗄️ 從 PostgreSQL 讀取資料
def get_fortune_from_db(sign, target_date):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url: return None
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
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

# 🧠 終極工業級升級：具有「伺服器繁忙自動重試」與「多重模型無痛降級」的翻譯器
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
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "【錯誤診斷】Render 後台找不到 GEMINI_API_KEY。"
        
    client = genai.Client(api_key=api_key)
    
    # 🌟 優先嘗試 2.0-flash，如果被塞爆或找不到，無縫接軌備援 1.5-flash
    models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash']
    last_error = ""
    
    for model_name in models_to_try:
        delay = 4  # 初始等待 4 秒
        for attempt in range(3):  # 每個模型嘗試 3 次
            try:
                print(f"嘗試使用模型 [{model_name}] 縮短 [{sign_name}] 運勢 (第 {attempt+1}/3 次)...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                ai_reply = response.text.strip()
                
                if len(ai_reply) > 250:
                    return ai_reply[:240] + "..."
                    
                return ai_reply
                
            except Exception as e:
                last_error = str(e)
                print(f"❌ 模型 [{model_name}] 失敗: {last_error}")
                
                # 📌 關鍵判定 1：如果是 404（模型不存在），不用重試了，直接中斷嘗試下一個備用模型！
                if "404" in last_error or "NOT_FOUND" in last_error or "not found" in last_error:
                    print("👉 偵測到 404 錯誤，直接切換到下一個備援模型...")
                    break
                
                # 📌 關鍵判定 2：新增攔截 503 UNAVAILABLE 與 500！遇到伺服器大塞車，乖乖等待重試
                if any(x in last_error for x in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500"]):
                    print(f"⚠️ 偵測到伺服器繁忙/配額限制，等待 {delay} 秒後重試...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    # 其他未知錯誤，也進行重試，確保最大生還率
                    time.sleep(delay)
                    delay *= 2
                    
    # 如果所有模型的所有重試都爆了，才回傳失敗
    return f"【AI 呼叫失敗】：{last_error[:100]}..."

def get_today_horoscope(sign_name):
    sign_map = {
        "牡羊座": 0, "金牛座": 1, "雙子座": 2, "巨蟹座": 3,
        "獅子座": 4, "处女座": 5, "天秤座": 6, "天蠍座": 7,
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
    
    print(f"⏰ 開始執行 12 星座運勢背景暖機作業，今日日期：{today_date}")
    
    for sign in signs:
        raw_fortune = get_today_horoscope(sign)
        
        if raw_fortune not in ["ERROR_SIGN", "ERROR_PARSE", "ERROR_CONN"]:
            short_fortune = ask_gemini_to_shorten(sign, raw_fortune)
            final_result = f"🔮【{sign}今日運勢】{short_fortune}"
            
            if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
                save_fortune_to_db(sign, final_result, today_date)
            else:
                print(f"❌ [{sign}] 暖機失敗，跳過寫入資料庫。")
                
        time.sleep(6)
    
    print("✨ 背景暖機作業結束！")

@app.get("/warmup")
def warmup_cache(background_tasks: BackgroundTasks):
    background_tasks.add_task(auto_fetch_all_signs)
    return {"status": "開始在背景自動抓取 12 星座運勢，並存入雲端資料庫！大約需時 80 秒。"}

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    if not sign:
        return "🔮 請提供星座名稱，例如: ?sign=雙子座"
        
    today_date = get_tw_today()
    
    # 🎯 優先去資料庫找今天的運勢 (0.01秒超高速)
    db_fortune = get_fortune_from_db(sign, today_date)
    if db_fortune:
        return db_fortune
        
    # 如果資料庫沒有，才即時抓取
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
