from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
import os
from typing import Optional # <<< Для Optional[str>
from fastapi.middleware.cors import CORSMiddleware # <<< Импорт CORSMiddleware

app = FastAPI()

# <<< Настройки CORS - ДОЛЖНЫ БЫТЬ САМЫМИ ПЕРВЫМИ >>>
# Разрешаем запросы с вашего домена админ-панели
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://zoomadmin.vercel.app"], # <<< Ваш точный домен без пробелов
    allow_credentials=True,
    allow_methods=["*"], # <<< Разрешаем все методы (GET, POST, OPTIONS и т.д.)
    allow_headers=["*"], # <<< Разрешаем все заголовки
)

# Получаем URL и ключ из переменных окружения (Vercel Environment Variables)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Не заданы SUPABASE_URL или SUPABASE_KEY в Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# <<< Исправленная модель Partner с Optional >>>
class Partner(BaseModel):
    id: str
    name: str
    referrer_id: Optional[str] = None
    telegram_id: Optional[str] = None

class Deal(BaseModel):
    id: str
    partner_id: str
    type: str
    amount: float
    date: Optional[str] = None # <<< Новое поле

class Payout(BaseModel):
    partner_id: str
    amount: float
    date: Optional[str] = None

@app.get("/")
def root():
    return {"message": "API работает!"}

@app.post("/partner")
def add_partner(partner: Partner):
    data, count = supabase.table("partners").insert(partner.dict(exclude_unset=True)).execute()
    return data

@app.post("/deal")
def add_deal(deal: Deal):
    """
    Добавляет новую сделку и запускает расчет бонусов.
    """
    try:
        print(f"[DEBUG] Начинаем обработку новой сделки: {deal.id}")
        # 1. <<< НОВОЕ: Проверяем, существует ли сделка >>>
        deal_check = supabase.table("deals").select("id").eq("id", deal.id).execute()
        if deal_check.data and len(deal_check.data) > 0:
            raise HTTPException(status_code=409, detail=f"Сделка с ID {deal.id} уже существует")
        # <<< КОНЕЦ НОВОГО: Проверяем, существует ли сделка >>>

        # 2. Сохраняем сделку (включая дату)
        data, count = supabase.table("deals").insert(deal.dict(exclude_unset=True)).execute() # <<< exclude_unset=True
        print(f"[DEBUG] Сделка {deal.id} сохранена в Supabase.")

        # 3. Рассчитываем бонусы (асинхронно или синхронно - зависит от вашей архитектуры)
        # В текущей реализации это синхронный вызов.
        calculate_bonuses(deal)
        print(f"[DEBUG] Расчет бонусов для сделки {deal.id} завершен.")

        return data
    except HTTPException:
        # Перебрасываем HTTPException без изменений
        raise 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при добавлении сделки: {str(e)}")

@app.post("/payout")
def add_payout(payout: Payout):
    """
    Добавляет новую запись о выплате.
    """
    try:
        print(f"[DEBUG] Добавляем выплату для партнера: {payout.partner_id}, сумма: {payout.amount}, дата: {payout.date}")
        # 1. Проверяем, существует ли партнёр
        partner_check = supabase.table("partners").select("id").eq("id", payout.partner_id).execute()
        if not partner_check.data or len(partner_check.data) == 0:
            raise HTTPException(status_code=404, detail="Partner not found")

        # 2. Подготавливаем данные для вставки
        payout_data = payout.dict(exclude_unset=True) # <<< exclude_unset=True

        # 3. Вставляем запись в таблицу payouts_history
        data, count = supabase.table("payouts_history").insert(payout_data).execute()
        print(f"[DEBUG] Выплата добавлена: {data}")

        return data
    except HTTPException:
        # Перебрасываем HTTPException без изменений
        raise 
    except Exception as e:
        print(f"[ERROR] Ошибка при добавлении выплаты: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error in add_payout: {str(e)}")

def calculate_bonuses(deal):
    # Получаем цепочку рефералов
    chain = []
    current_id = deal.partner_id
    level = 0

    while current_id and level < 3:
        response = supabase.table("partners").select("referrer_id").eq("id", current_id).execute()
        # Проверяем, есть ли данные в ответе И содержит ли список данных хотя бы один элемент
        if response.data and len(response.data) > 0:
            referrer = response.data[0].get("referrer_id") # Используем .get для безопасности
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
            # net = 50000  # УБРАТЬ ЭТУ СТРОКУ, ЕСЛИ ВЫ УЖЕ ВНОСИТЕ "ЧИСТУЮ" КОМИССИЮ
            net = deal.amount # <<< ИСПОЛЬЗУЕМ ВСЮ СУММУ КРЕДИТА
            if item["level"] == 1:
                bonus = net * 0.08  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
            elif item["level"] == 2:
                bonus = net * 0.05  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ
            elif item["level"] == 3:
                bonus = net * 0.02  # ИЛИ ВАШ НОВЫЙ ПРОЦЕНТ

        bonus = round(bonus) # Убедимся, что это число
        print(f"[DEBUG] Рассчитанный бонус: {bonus}")

        # Подготавливаем данные бонуса для вставки
        bonus_data = {
            "deal_id": deal.id,
            "partner_id": deal.partner_id, # ID партнера, совершившего сделку
            "referrer_id": item["referrer_id"], # ID партнера, который получает бонус
            "level": item["level"],
            "bonus": round(bonus)
        }
        print(f"[DEBUG] Подготовлены данные бонуса для вставки: {bonus_data}")
        # Вставляем бонус в таблицу
        supabase.table("bonuses").insert(bonus_data).execute()

@app.get("/bonuses")
def get_all_bonuses():
    """
    Возвращает список всех бонусов с именами партнёров и датами сделок.
    """
    try:
        print("[DEBUG] Запрашиваем все бонусы...")
        data, count = supabase.table("bonuses").select("*").execute()
        bonuses = data[1] if data[1] else []
        print(f"[DEBUG] Найдено бонусов: {len(bonuses)}")

        # Получаем список всех партнёров для подстановки имён
        partners_data_response = supabase.table("partners").select("*").execute()
        partners_map = {p['id']: p for p in partners_data_response.data} if partners_data_response.data else {}
        print(f"[DEBUG] Загружен список партнёров: {len(partners_map)}")

        # Получаем список всех сделок для подстановки дат
        deals_data_response = supabase.table("deals").select("*").execute()
        deals_map = {d['id']: d for d in deals_data_response.data} if deals_data_response.data else {}
        print(f"[DEBUG] Загружен список сделок: {len(deals_map)}")

        # Обогащаем бонусы именами и датами
        enriched_bonuses = []
        for b in bonuses:
            enriched_bonus = b.copy()
            # Имя партнёра, совершившего сделку
            partner = partners_map.get(b['partner_id'])
            enriched_bonus['partner_name'] = partner['name'] if partner else "Неизвестный"
            # Дата сделки
            deal = deals_map.get(b['deal_id'])
            print(f"[DEBUG] deal_date для {b['deal_id']}: {deal['date'] if deal else 'None'}")
            enriched_bonus['deal_date'] = deal['date'] if deal and deal.get('date') else None
            enriched_bonuses.append(enriched_bonus)

        print("[DEBUG] Бонусы обогащены именами и датами.")
        return enriched_bonuses
    except Exception as e:
        print(f"[ERROR] Ошибка в get_all_bonuses: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при получении бонусов: {str(e)}")

@app.get("/bonuses/{partner_id}")
def get_bonuses(partner_id: str):
    data, count = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
    return data[1]

@app.get("/partner/{partner_id}")
def get_partner(partner_id: str):
    data, count = supabase.table("partners").select("*").eq("id", partner_id).execute()
    if not data[1] or len(data[1]) == 0:
        raise HTTPException(status_code=404, detail="Partner not found")
    return data[1][0]

@app.get("/partner")  # <<< Новый маршрут для загрузки списка перекупов
def get_all_partners():
    """
    Возвращает список всех партнеров.
    """
    try:
        data, count = supabase.table("partners").select("*").execute()
        return data[1]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении списка партнеров: {str(e)}")

@app.get("/referrals/{partner_id}")
def get_referrals(partner_id: str):
    data, count = supabase.table("partners").select("*").eq("referrer_id", partner_id).execute()
    return data[1]

# <<< НОВОЕ: Маршрут для статистики по пользователю >>>
@app.get("/deals/partner/{partner_id}")
def get_deals_for_partner(partner_id: str):
    """
    Возвращает статистику и данные для конкретного партнера.
    Добавлено: Возврат списка `deals`.
    """
    try:
        print(f"[DEBUG] Запрашиваем статистику для партнера: {partner_id}")
        # 1. Получаем все сделки партнера
        deals_response = supabase.table("deals").select("*").eq("partner_id", partner_id).execute()
        deals = deals_response.data if deals_response.data else []
        print(f"[DEBUG] Найдено сделок: {len(deals)}")

        # 2. Получаем бонусы, которые получил партнер как реферер (уровень 1 от его рефералов)
        bonuses_received_response = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
        bonuses_received = bonuses_received_response.data if bonuses_received_response.data else []
        print(f"[DEBUG] Найдено бонусов за рефералов: {len(bonuses_received)}")

        # 3. Получаем список рефералов 1-го уровня
        referrals_response = supabase.table("partners").select("id").eq("referrer_id", partner_id).execute()
        referrals = [r['id'] for r in referrals_response.data] if referrals_response.data else []
        print(f"[DEBUG] Найдено рефералов 1-го уровня: {len(referrals)}")

        # 4. Считаем статистику
        total_deals = len(deals)
        total_commission = sum(d.get('amount', 0) for d in deals)
        total_bonuses = sum(b.get('bonus', 0) for b in bonuses_received)
        referrals_count = len(referrals)
        print(f"[DEBUG] Статистика рассчитана: Deals={total_deals}, Commission={total_commission}, Bonuses={total_bonuses}, Referrals={referrals_count}")

        # 5. <<< НОВОЕ: Получаем имя партнера >>>
        partner_name = "Unknown"
        partner_data_response = supabase.table("partners").select("name").eq("id", partner_id).execute()
        if partner_data_response.data and len(partner_data_response.data) > 0:
            partner_name = partner_data_response.data[0]["name"]
        print(f"[DEBUG] Имя партнера: {partner_name}")
        # <<< КОНЕЦ НОВОГО: Получаем имя партнера >>>

        # 6. Формируем ответ
        result = {
            "partner_id": partner_id,
            "partner_name": partner_name, # <<< Добавлено
            "stats": {
                "total_deals": total_deals,
                "total_commission": total_commission,
                "total_bonuses": total_bonuses,
                "referrals_count": referrals_count
            },
            "deals": deals, # <<< Добавлено
            "bonuses_received": bonuses_received
        }

        return result

    except Exception as e:
        print(f"[ERROR] Ошибка в get_deals_for_partner для {partner_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error in get_deals_for_partner: {str(e)}")

@app.get("/payouts")
def get_payouts_summary():
    """
    Возвращает сводку выплат по каждому партнеру: общая сумма бонусов, выплачено, остаток.
    """
    try:
        print("[DEBUG] Запрашиваем сводку выплат...")
        # 1. Получаем все бонусы
        bonuses_data_response = supabase.table("bonuses").select("referrer_id, bonus").execute()
        bonuses = bonuses_data_response.data if bonuses_data_response.data else []
        print(f"[DEBUG] Найдено бонусов: {len(bonuses)}")

        # 2. Получаем все выплаты
        payouts_data_response = supabase.table("payouts_history").select("partner_id, amount").execute()
        payouts = payouts_data_response.data if payouts_data_response.data else []
        print(f"[DEBUG] Найдено выплат: {len(payouts)}")

        # 3. Суммируем бонусы по каждому рефереру
        bonus_map = {}
        for b in bonuses:
            ref_id = b["referrer_id"]
            if ref_id not in bonus_map:
                # Получаем имя партнёра
                p_data_response = supabase.table("partners").select("name").eq("id", ref_id).execute()
                # Проверяем, есть ли данные о партнере
                if p_data_response.data and len(p_data_response.data) > 0:
                    name = p_data_response.data[0]["name"]
                else:
                    name = "Unknown"
                bonus_map[ref_id] = {"name": name, "total_bonuses": 0}
            bonus_map[ref_id]["total_bonuses"] += b["bonus"]

        # 4. Суммируем выплаты по каждому партнёру
        payout_map = {}
        for p in payouts:
            partner_id = p["partner_id"]
            if partner_id not in payout_map:
                payout_map[partner_id] = 0
            payout_map[partner_id] += p["amount"]

        # 5. Формируем сводку
        result = []
        for ref_id, bonus_info in bonus_map.items():
            total_bonuses = bonus_info["total_bonuses"]
            paid = payout_map.get(ref_id, 0)
            balance = total_bonuses - paid
            result.append({
                "id": ref_id,
                "name": bonus_info["name"],
                "total_bonuses": total_bonuses, # <<< Новое
                "paid": paid, # <<< Новое
                "balance": balance # <<< Новое
            })

        print("[DEBUG] Сводка выплат рассчитана.")
        return result

    except Exception as e:
        print(f"[ERROR] Ошибка в get_payouts_summary: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error in get_payouts_summary: {str(e)}")
