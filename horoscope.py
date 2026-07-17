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
    if not os.environ.get("GROQ_API_KEY"):
        print("⚠️ 警告：未設定 GROQ_API_KEY，主要AI服務無法使用，會直接fallback到OpenRouter")
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("⚠️ 警告：未設定 OPENROUTER_API_KEY，備援AI服務也無法使用！")
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

# 🧠 產生統一的 prompt
def build_prompt(long_text):
    return (
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

# ⭐ 主力：Groq（速度快、額度穩，跟 OpenRouter 是完全獨立的免費額度）
def call_groq(sign_name, prompt):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("⚠️ GROQ_API_KEY 未設定，跳過 Groq，改用 OpenRouter")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(2):
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 160,
                    "temperature": 0.7
                },
                timeout=20
            )
            data = response.json()
            if "choices" in data:
                reply = data['choices'][0]['message'].get('content')
                if reply:
                    reply = reply.strip()
                    if "User Safety" not in reply:
                        return reply
                print(f"⚠️ [{sign_name}] Groq 回傳了空內容")
                return None

            print(f"⚠️ [{sign_name}] Groq 回傳非預期格式，status={response.status_code}, body={data}")
            if response.status_code == 429:
                # Groq 的 429 通常是短時間額度用完，等 retry-after header 或固定秒數
                retry_after = int(response.headers.get("retry-after", 10))
                retry_after = min(retry_after + 2, 20)
                print(f"⏳ [{sign_name}] Groq 限流，等待 {retry_after} 秒後重試...")
                time.sleep(retry_after)
                continue
            return None
        except Exception as e:
            print(f"⚠️ [{sign_name}] Groq 呼叫發生例外: {e}")
            return None
    return None

# 🔁 備援：OpenRouter（Groq 失敗時才會用到）
def call_openrouter(sign_name, prompt):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️ OPENROUTER_API_KEY 未設定，無備援可用")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    models = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/free",
    ]

    for model in models:
        for attempt in range(2):
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
                    reply = data['choices'][0]['message'].get('content')
                    if not reply:
                        print(f"⚠️ [{sign_name}] 模型 {model} 回傳了空內容，換下一個模型")
                        break
                    reply = reply.strip()
                    if "User Safety" in reply: continue
                    return reply

                print(f"⚠️ [{sign_name}] 模型 {model} 回傳非預期格式，status={response.status_code}, body={data}")

                if response.status_code == 429:
                    retry_after = data.get("error", {}).get("metadata", {}).get("retry_after_seconds", 15)
                    retry_after = min(int(retry_after) + 2, 35)
                    print(f"⏳ [{sign_name}] 遇到限流，等待 {retry_after} 秒後重試...")
                    time.sleep(retry_after)
                    continue
                else:
                    break
            except Exception as e:
                print(f"⚠️ [{sign_name}] 模型 {model} 呼叫發生例外: {e}")
                break
    return None

# 🎯 統一入口：先試 Groq，失敗才 fallback 到 OpenRouter
def ask_ai_to_shorten(sign_name, long_text, is_background=False):
    prompt = build_prompt(long_text)

    reply = call_groq(sign_name, prompt)
    if reply:
        return reply

    print(f"↪️ [{sign_name}] Groq 失敗，改用 OpenRouter 備援...")
    return call_openrouter(sign_name, prompt)

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
            short = ask_ai_to_shorten(sign, raw, is_background=True)
            if short:  # ⭐ 只有真正成功才寫入DB，避免整天卡死在失敗文字
                save_fortune_to_db(sign, f"🔮【{sign}今日運勢】{short}", get_tw_today())
                report.append(f"✓ {sign}")
            else:
                report.append(f"✗ {sign} (AI失敗，未寫入DB，下次查詢會重試)")
        else:
            report.append(f"✗ {sign} (爬蟲失敗: {raw})")
        time.sleep(8)  # ⭐ 從5秒拉長到8秒，降低撞到上游限流的機率
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

def check_admin_key(key: str):
    """⭐ 檢查管理密鑰是否正確，避免公開網址被任何人拿去刪資料"""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key:
        return False, "伺服器未設定 ADMIN_KEY，請先在 Render 環境變數加上 ADMIN_KEY"
    if key != admin_key:
        return False, "密鑰錯誤，無權限執行此操作"
    return True, ""

@app.api_route("/admin/delete-sign", methods=["GET", "DELETE"])
def admin_delete_sign(sign: str = "", key: str = ""):
    """刪除單一星座的資料，例如 /admin/delete-sign?sign=水瓶座&key=你的密鑰"""
    ok, msg = check_admin_key(key)
    if not ok:
        return {"error": msg}
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute("DELETE FROM horoscope WHERE sign = %s;", (sign,))
        deleted = cur.rowcount
        conn.commit()
        cur.close(); conn.close()
        return {"status": f"已刪除 {deleted} 筆資料", "sign": sign}
    except Exception as e:
        return {"error": str(e)}

@app.api_route("/admin/clear-invalid", methods=["GET", "DELETE"])
def admin_clear_invalid(key: str = ""):
    """清除所有「不是12星座」的髒資料（例如打錯字、亂測試留下的資料），例如 /admin/clear-invalid?key=你的密鑰"""
    ok, msg = check_admin_key(key)
    if not ok:
        return {"error": msg}
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(VALID_SIGNS))
        cur.execute(f"DELETE FROM horoscope WHERE sign NOT IN ({placeholders});", tuple(VALID_SIGNS))
        deleted = cur.rowcount
        conn.commit()
        cur.close(); conn.close()
        return {"status": f"已清除 {deleted} 筆非12星座的髒資料"}
    except Exception as e:
        return {"error": str(e)}

@app.api_route("/admin/clear-all", methods=["GET", "DELETE"])
def admin_clear_all(key: str = ""):
    """清空整張表格，例如 /admin/clear-all?key=你的密鑰"""
    ok, msg = check_admin_key(key)
    if not ok:
        return {"error": msg}
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE horoscope;")
        conn.commit()
        cur.close(); conn.close()
        return {"status": "已清空整張資料表"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/horoscope")
def read_horoscope(sign: str = ""):
    sign = sign.strip()

    # ⭐ 白名單驗證：只接受 12 星座，其他一律拒絕、且不寫入DB
    if sign not in VALID_SIGNS:
        return f"您輸入的「{sign}」，請重新輸入十二星座的名稱來看今日運勢，例如：牡羊座、金牛座..."

    db_res = get_fortune_from_db(sign, get_tw_today())
    if db_res:
        return db_res

    raw = get_today_horoscope(sign)
    if "ERROR" in raw:
        # ⭐ 爬蟲失敗就不要浪費 AI 額度，也不要存入DB
        return f"🔮【{sign}】運勢來源暫時抓取失敗，請稍後再試一次！"

    short = ask_ai_to_shorten(sign, raw, is_background=False)
    if not short:
        # ⭐ AI失敗不寫入DB，讓下一次查詢有機會重新成功
        return f"🔮【{sign}】AI 目前忙碌中，請稍後再試一次！"

    final = f"🔮【{sign}今日運勢】{short}"
    save_fortune_to_db(sign, final, get_tw_today())
    return final

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
