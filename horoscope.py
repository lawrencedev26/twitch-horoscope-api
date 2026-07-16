import os
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from fastapi import FastAPI, BackgroundTasks
import urllib3
from datetime import datetime, timezone, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

# ⭐ 12 星座白名單（唯一合法輸入來源，其他一律拒絕）
SIGN_MAP = {"牡羊座":0,"金牛座":1,"雙子座":2,"巨蟹座":3,"獅子座":4,"處女座":5,
            "天秤座":6,"天蠍座":7,"射手座":8,"摩羯座":9,"水瓶座":10,"雙魚座":11}
VALID_SIGNS = set(SIGN_MAP.keys())

# 🚀 程式啟動時，自動檢查並建立資料庫表格
@app.on_event("startup")
def startup_db_client():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("⚠️ 警告：未設定 DATABASE_URL 環境變數")
        return
    # ⭐ 開機時就檢查 API KEY 是否存在，方便你在 Render Logs 第一時間發現問題
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("⚠️ 警告：未設定 OPENROUTER_API_KEY 環境變數，AI 一定會失敗！")
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

# 🧠 純 OpenRouter 翻譯器
def ask_openrouter_to_shorten(sign_name, long_text, is_background=False):
    prompt = (
        f"你現在一位女性占卜師，感覺嚴肅且溫柔，還有修習過心理學碩士，非常體貼的占卜師。\n\n"
        f"【絕對命令】：請將下方運勢長文濃縮成『大約 120 到 150 字左右』的精闢短評。\n"
        f"【規則要求】：\n"
        f"1. 必須包含運勢核心重點。\n"
        f"2. 絕對只能使用「繁體中文」回答，嚴禁出現任何英文。\n"
        f"3. 語氣調侃，絕對不要有換行符號。\n"
        f"4. 嚴禁出現 'User Safety' 或 AI 分析字樣。\n"
        f"5. 最後一句話必須完整，並以全形句號「。」作結尾。\n\n"
        f"【運勢長文】：\n{long_text}"
    )

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY 未設定，無法呼叫 AI")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # ⭐ 更新為目前 (2026/07) 仍在 OpenRouter 上可用的免費模型
    # 注意：google/gemini 系列目前在 OpenRouter 已經沒有免費模型了，換成其他免費模型備援
    models = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat-v3-0324:free",
        "qwen/qwen2.5-vl-72b-instruct:free",
    ]

    for model in models:
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 160,
                    "temperature": 0.7
                },
                timeout=20
            )
            data = response.json()
            if "choices" in data:
                reply = data['choices'][0]['message']['content'].strip()
                if "User Safety" in reply: continue
                return reply
            else:
                # ⭐ 關鍵：把真正的錯誤原因印出來，之後看 Render Logs 就知道原因
                print(f"⚠️ [{sign_name}] 模型 {model} 回傳非預期格式，status={response.status_code}, body={data}")
        except Exception as e:
            print(f"⚠️ [{sign_name}] 模型 {model} 呼叫發生例外: {e}")
            continue
    return None  # ⭐ 改成回傳 None，而不是騙人的「呼叫失敗」文字，方便上層判斷是否該存DB

def get_today_horoscope(sign_name):
    sign_id = SIGN_MAP.get(sign_name)
    if sign_id is None: return "ERROR_SIGN"
    url = f"https://astro.click108.com.tw/daily_{sign_id}.php?iAstro={sign_id}"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=8)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")
        content = soup.find(class_="TODAY_CONTENT")
        return content.text.replace("\n", " ").strip() if content else "ERROR_PARSE"
    except Exception as e:
        print(f"❌ [{sign_name}] 爬蟲失敗: {e}")
        return "ERROR_CONN"

def auto_fetch_all_signs():
    signs = list(SIGN_MAP.keys())
    report = []
    for sign in signs:
        raw = get_today_horoscope(sign)
        if "ERROR" not in raw:
            short = ask_openrouter_to_shorten(sign, raw, is_background=True)
            if short:  # ⭐ 只有真正成功才寫入DB，避免整天卡死在失敗文字
                save_fortune_to_db(sign, f"🔮【{sign}今日運勢】{short}", get_tw_today())
                report.append(f"✓ {sign}")
            else:
                report.append(f"✗ {sign} (AI失敗，未寫入DB，下次查詢會重試)")
        else:
            report.append(f"✗ {sign} (爬蟲失敗: {raw})")
        time.sleep(5)
    return report

@app.get("/warmup")
def warmup_cache(background_tasks: BackgroundTasks):
    background_tasks.add_task(auto_fetch_all_signs)
    return {"status": "開始在背景自動暖機！"}

@app.get("/force-warmup")
def force_warmup():
    return {"report": auto_fetch_all_signs()}

@app.get("/check-db")
def check_database():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT sign, fortune_text FROM horoscope;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{"星座": r[0], "預覽": r[1][:20]} for r in rows]

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    sign = sign.strip()

    # ⭐ 白名單驗證：只接受 12 星座，其他一律拒絕、且不寫入DB
    if sign not in VALID_SIGNS:
        return f"請輸入正確的星座名稱喔，例如：牡羊座、金牛座... (你輸入的「{sign}」不是有效星座)"

    db_res = get_fortune_from_db(sign, get_tw_today())
    if db_res:
        return db_res

    raw = get_today_horoscope(sign)
    if "ERROR" in raw:
        # ⭐ 爬蟲失敗就不要浪費 AI 額度，也不要存入DB
        return f"🔮【{sign}】運勢來源暫時抓取失敗，請稍後再試一次！"

    short = ask_openrouter_to_shorten(sign, raw, is_background=False)
    if not short:
        # ⭐ AI失敗不寫入DB，讓下一次查詢有機會重新成功
        return f"🔮【{sign}】AI 目前忙碌中，請稍後再試一次！"

    final = f"🔮【{sign}今日運勢】{short}"
    save_fortune_to_db(sign, final, get_tw_today())
    return final

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
