from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
import os
from fastapi.middleware.cors import CORSMiddleware  # <<< Уже добавлено

app = FastAPI()

# <<< Добавляем настройки CORS >>>
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Можно указать "https://zoomadmin.vercel.app" для большей безопасности
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Получаем URL и ключ из переменных окружения (Vercel Environment Variables)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Не заданы SUPABASE_URL или SUPABASE_KEY в Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class Partner(BaseModel):
    id: str
    name: str
    referrer_id: str = None
    telegram_id: str = None

class Deal(BaseModel):
    id: str
    partner_id: str
    type: str
    amount: float

@app.get("/")
def root():
    return {"message": "API работает!"}

@app.post("/partner")
def add_partner(partner: Partner):
    data, count = supabase.table("partners").insert(partner.dict()).execute()
    return data

@app.post("/deal")
def add_deal(deal: Deal):
    # Сохраняем сделку
    data, count = supabase.table("deals").insert(deal.dict()).execute()

    # Рассчитываем бонусы
    calculate_bonuses(deal)

    return data

def calculate_bonuses(deal):
    # Получаем цепочку рефералов
    chain = []
    current_id = deal.partner_id
    level = 0

    while current_id and level < 3:
        response = supabase.table("partners").select("referrer_id").eq("id", current_id).execute()
        if response.data: # <<< ИСПРАВЛЕНО: Проверяем, есть ли данные
            referrer = response.data[0]["referrer_id"]
            if referrer:
                chain.append({"level": level + 1, "referrer_id": referrer})
            current_id = referrer
        else:
            break
        level += 1

    # Рассчитываем бонусы по цепочке
    for item in chain:
        bonus = 0
        if deal.type == "Продажа":
            # net = deal.amount - 10000  # УБРАТЬ ЭТУ СТРОКУ, ЕСЛИ ВЫ УЖЕ ВНОСИТЕ "ЧИСТУЮ" КОМИССИЮ
            net = deal.amount # <<< ИСПОЛЬЗУЕМ ВСЮ КОМИССИЮ
            if item["level"] == 1:
                bonus = net * 0.06  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
            elif item["level"] == 2:
                bonus = net * 0.04  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
            elif item["level"] == 3:
                bonus = net * 0.02  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
        elif deal.type == "Кредит":
            if item["level"] == 1:
                bonus = 50000 * 0.08  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
            elif item["level"] == 2:
                bonus = 50000 * 0.05  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
            elif item["level"] == 3:
                bonus = 50000 * 0.02  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ

        # Сохраняем бонус в базу
        bonus_data = {
            "deal_id": deal.id,
            "partner_id": deal.partner_id,
            "referrer_id": item["referrer_id"],
            "level": item["level"],
            "bonus": round(bonus)
        }
        supabase.table("bonuses").insert(bonus_data).execute()

@app.get("/bonuses")
def get_all_bonuses():
    data, count = supabase.table("bonuses").select("*").execute()
    return data[1]

@app.get("/bonuses/{partner_id}")
def get_bonuses(partner_id: str):
    data, count = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
    return data[1]

@app.get("/payouts")
def get_payouts():
    # Суммируем бонусы по каждому рефереру
    data, count = supabase.table("bonuses").select("referrer_id, bonus").execute()
    bonuses = data[1]

    payout_map = {}
    for b in bonuses:
        ref_id = b["referrer_id"]
        if ref_id not in payout_map:
            # Получаем имя партнёра
            p_data, _ = supabase.table("partners").select("name").eq("id", ref_id).execute()
            name = p_data[1][0]["name"] if p_data[1] else "Unknown"
            payout_map[ref_id] = {"name": name, "total": 0}
        payout_map[ref_id]["total"] += b["bonus"]

    result = [{"id": k, "name": v["name"], "total": v["total"]} for k, v in payout_map.items()]
    return result

@app.get("/partner/{partner_id}")
def get_partner(partner_id: str):
    data, count = supabase.table("partners").select("*").eq("id", partner_id).execute()
    if not data[1]:
        raise HTTPException(status_code=404, detail="Partner not found")
    return data[1][0]

@app.get("/partner")
def get_all_partners():
    data, count = supabase.table("partners").select("*").execute()
    return data[1]

@app.get("/referrals/{partner_id}")
def get_referrals(partner_id: str):
    data, count = supabase.table("partners").select("*").eq("referrer_id", partner_id).execute()
    return data[1]

# <<< НОВОЕ: Маршрут для статистики по пользователю (БЕЗ аутентификации) >>>
@app.get("/deals/partner/{partner_id}")
def get_deals_for_partner(partner_id: str):
    # Получаем все сделки конкретного партнёра
    deals_data, count = supabase.table("deals").select("*").eq("partner_id", partner_id).execute()
    deals = deals_data[1] if deals_data[1] else []

    # Получаем бонусы, которые получил *этот партнёр* как реферер (уровень 1 от его рефералов)
    # Это бонусы, где referrer_id == partner_id
    bonuses_data, count = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
    bonuses = bonuses_data[1] if bonuses_data[1] else []

    # Получаем рефералов 1-го уровня
    referrals_data, count = supabase.table("partners").select("id").eq("referrer_id", partner_id).execute()
    referrals = [r['id'] for r in referrals_data[1]] if referrals_data[1] else []

    # Собираем статистику
    total_deals = len(deals)
    total_commission = sum(d['amount'] for d in deals)
    total_bonuses = sum(b['bonus'] for b in bonuses)

    # Формируем ответ
    result = {
        "partner_id": partner_id,
        "stats": {
            "total_deals": total_deals,
            "total_commission": total_commission,
            "total_bonuses": total_bonuses,
            "referrals_count": len(referrals)
        },
        "deals": deals,
        "bonuses_received": bonuses # Бонусы, полученные *им* за рефералов
    }

    return result
