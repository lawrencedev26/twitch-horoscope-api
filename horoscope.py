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

def ask_gemini_to_shorten(sign_name, long_text, is_background=False):
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
    
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    
    # ----------------------------------------------------
    # 🚀 第一引擎：嘗試使用 Google Gemini
    # ----------------------------------------------------
    if gemini_key and "這裡" not in gemini_key:
        try:
            client = genai.Client(api_key=gemini_key)
            models_to_try = ['gemini-3.5-flash', 'gemini-3.1-flash-lite']
            max_attempts = 3 if is_background else 1 
            
            for model_name in models_to_try:
                delay = 4
                for attempt in range(max_attempts):
                    try:
                        if is_background:
                            print(f"嘗試使用 Gemini 模型 [{model_name}] 縮短 [{sign_name}] 運勢...", flush=True)
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                        )
                        ai_reply = response.text.strip()
                        if len(ai_reply) > 250:
                            return ai_reply[:240] + "..."
                        return ai_reply
                    except Exception as gemini_err:
                        err_str = str(gemini_err)
                        # 📌 如果偵測到硬性帳單欠費(Credits depleted)，Gemini 直接棄守，改用備援引擎！
                        if "prepayment credits" in err_str or "depleted" in err_str:
                            print("⚠️ Gemini 帳戶欠費凍結，放棄重試，準備啟動備援 OpenRouter 引擎...", flush=True)
                            raise RuntimeError("Gemini Billing Locked")
                            
                        if is_background and any(x in err_str for x in ["429", "503", "500"]):
                            time.sleep(delay)
                            delay *= 2
                        else:
                            break
        except Exception:
            pass # 這裡拋出的異常，會引導程式進入下方的 OpenRouter 備援防線

    if openrouter_key and "這裡" not in openrouter_key:
        try:
            if is_background:
                print(f"🔗 [備援啟動] 正在使用 OpenRouter 免費引擎為 [{sign_name}] 算命...", flush=True)
            
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json"
            }
            # openrouter/free 會自動挑選 2026 年最新、最快的免費大模型 (如 Llama 等)
            payload = {
                "model": "openrouter/free",
                "messages": [{"role": "user", "content": prompt}]
            }
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                ai_reply = response.json()['choices'][0]['message']['content'].strip()
                if len(ai_reply) > 250:
                    return ai_reply[:240] + "..."
                return ai_reply
            else:
                print(f"❌ OpenRouter 失敗 (HTTP {response.status_code}): {response.text}", flush=True)
        except Exception as router_err:
            print(f"❌ OpenRouter 連線異常: {router_err}", flush=True)
            
    return "【AI 呼叫失敗】：Gemini 帳單鎖卡，且未設定有效的 OPENROUTER_API_KEY 備援引擎。"

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

def auto_fetch_all_signs():
    signs = [
        "牡羊座", "金牛座", "雙子座", "巨蟹座",
        "獅子座", "處女座", "天秤座", "天蠍座",
        "射手座", "摩羯座", "水瓶座", "雙魚座"
    ]
    today_date = get_tw_today()
    report = []
    
    msg_start = f"⏰ 開始執行 12 星座運勢背景暖機作業，今日日期：{today_date}"
    print(msg_start, flush=True)
    report.append(msg_start)
    
    for sign in signs:
        raw_fortune = get_today_horoscope(sign)
        
        if raw_fortune not in ["ERROR_SIGN", "ERROR_PARSE", "ERROR_CONN"]:
            short_fortune = ask_gemini_to_shorten(sign, raw_fortune, is_background=True)
            final_result = f"🔮【{sign}今日運勢】{short_fortune}"
            
            if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
                save_fortune_to_db(sign, final_result, today_date)
                msg_success = f"✓ [{sign}] 成功寫入資料庫！"
                print(msg_success, flush=True)
                report.append(msg_success)
            else:
                msg_fail = f"❌ [{sign}] 暖機失敗，原因: {short_fortune}"
                print(msg_fail, flush=True)
                report.append(msg_fail)
                
        time.sleep(6)
    
    msg_end = "✨ 暖機作業結束！"
    print(msg_end, flush=True)
    report.append(msg_end)
    
    return report

@app.get("/warmup")
def warmup_cache(background_tasks: BackgroundTasks):
    background_tasks.add_task(auto_fetch_all_signs)
    return {"status": "開始在背景自動抓取 12 星座運勢，並存入雲端資料庫！大約需時 80 秒。"}

@app.get("/force-warmup")
def force_warmup():
    """強制暖機：直接在網頁等待並顯示結果，方便除錯"""
    report = auto_fetch_all_signs()
    return {"status": "強制暖機完成", "report": report}

@app.get("/check-db")
def check_database():
    """直接偷看資料庫裡面到底存了幾筆資料，以及存了什麼"""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url: 
        return {"status": "找不到 DATABASE_URL 環境變數"}
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        cursor.execute("SELECT sign, target_date, left(fortune_text, 15) FROM horoscope;")
        rows = cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                "星座": row[0], 
                "寫入日期": row[1], 
                "運勢預覽": row[2] + "..."
            })
            
        return {
            "目前總筆數": len(result), 
            "詳細清單": result
        }
    except Exception as e:
        return {"error": f"讀取失敗: {e}"}
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

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
        
    short_fortune = ask_gemini_to_shorten(sign, raw_fortune, is_background=False)
    final_result = f"🔮【{sign}今日運勢】{short_fortune}"
    
    if "【AI 呼叫失敗】" not in final_result and "錯誤診斷" not in final_result:
        save_fortune_to_db(sign, final_result, today_date)
        
    return final_result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
