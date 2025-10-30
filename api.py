from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
import os
from typing import Optional # <<< Для Optional[str>
from fastapi.middleware.cors import CORSMiddleware # <<< Импорт CORSMiddleware

app = FastAPI()

# <<< Настройки CORS - ДОЛЖНЫ БЫТЬ САМЫМИ ПЕРВЫМИ >>>
# Исправлено: Убраны лишние пробелы в URL
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

# Проверка наличия переменных окружения критически важна
if not SUPABASE_URL or not SUPABASE_KEY:
    # Эта ошибка приведет к FUNCTION_INVOCATION_FAILED если не будет поймана на старте
    # Лучше логировать это явно
    print("CRITICAL: SUPABASE_URL or SUPABASE_KEY is missing!")
    raise ValueError("Не заданы SUPABASE_URL или SUPABASE_KEY в Environment Variables")

# Создание клиента Supabase
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

@app.get("/")
def root():
    """Корневой маршрут для проверки работы API."""
    return {"message": "API работает!"}

@app.post("/partner")
def add_partner(partner: Partner):
    """
    Добавляет нового партнера.
    """
    try:
        # exclude_unset=True гарантирует, что None значения не будут отправлены в Supabase,
        # если вы используете Optional поля.
        data, count = supabase.table("partners").insert(partner.dict(exclude_unset=True)).execute()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при добавлении партнера: {str(e)}")

@app.post("/deal")
def add_deal(deal: Deal):
    """
    Добавляет новую сделку и запускает расчет бонусов.
    """
    try:
        # 1. Сохраняем сделку
        data, count = supabase.table("deals").insert(deal.dict()).execute()

        # 2. Рассчитываем бонусы (асинхронно или синхронно - зависит от вашей архитектуры)
        # В текущей реализации это синхронный вызов.
        calculate_bonuses(deal)

        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при добавлении сделки: {str(e)}")

def calculate_bonuses(deal: Deal):
    """
    Рассчитывает бонусы для рефереров партнера.
    """
    try:
        # Получаем цепочку рефералов (до 3 уровней)
        chain = []
        current_id = deal.partner_id
        level = 0

        while current_id and level < 3:
            # Запрос к Supabase для получения referrer_id
            response = supabase.table("partners").select("referrer_id").eq("id", current_id).execute()
            
            # Проверяем, есть ли данные в ответе И содержит ли список данных хотя бы один элемент
            if response.data and len(response.data) > 0:
                referrer = response.data[0].get("referrer_id") # Используем .get для безопасности
                if referrer:
                    chain.append({"level": level + 1, "referrer_id": referrer})
                current_id = referrer
            else:
                # Если партнера с таким id нет или у него нет referrer_id, цепочка обрывается
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

            # Подготавливаем данные бонуса для вставки
            bonus_data = {
                "deal_id": deal.id,
                "partner_id": deal.partner_id, # ID партнера, совершившего сделку
                "referrer_id": item["referrer_id"], # ID партнера, который получает бонус
                "level": item["level"],
                "bonus": round(bonus)
            }
            # Вставляем бонус в таблицу
            supabase.table("bonuses").insert(bonus_data).execute()
    
    except Exception as e:
        # Логируем ошибку, но не прерываем выполнение основного запроса
        print(f"Ошибка при расчете бонусов для сделки {deal.id}: {e}")
        # Можно добавить логику повторной попытки или уведомления


@app.get("/bonuses")
def get_all_bonuses():
    """
    Возвращает список всех бонусов.
    """
    try:
        data, count = supabase.table("bonuses").select("*").execute()
        # data[0] обычно содержит тип операции ('SELECT'), data[1] - сами данные
        return data[1] 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении бонусов: {str(e)}")

@app.get("/bonuses/{partner_id}")
def get_bonuses(partner_id: str):
    """
    Возвращает бонусы для конкретного партнера (по referrer_id).
    """
    try:
        data, count = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
        return data[1]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении бонусов партнера {partner_id}: {str(e)}")

@app.get("/payouts")
def get_payouts():
    """
    Возвращает сводку выплат по каждому партнеру (сумма бонусов).
    """
    try:
        # Суммируем бонусы по каждому рефереру
        data, count = supabase.table("bonuses").select("referrer_id, bonus").execute()
        bonuses = data[1] # data[1] содержит список словарей

        payout_map = {}
        for b in bonuses:
            ref_id = b["referrer_id"]
            if ref_id not in payout_map:
                # Получаем имя партнёра
                p_data_response = supabase.table("partners").select("name").eq("id", ref_id).execute()
                # Проверяем, есть ли данные о партнере
                if p_data_response.data and len(p_data_response.data) > 0:
                    name = p_data_response.data[0]["name"]
                else:
                    name = "Unknown"
                payout_map[ref_id] = {"name": name, "total": 0}
            payout_map[ref_id]["total"] += b["bonus"]

        result = [{"id": k, "name": v["name"], "total": v["total"]} for k, v in payout_map.items()]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при расчете выплат: {str(e)}")

@app.get("/partner/{partner_id}")
def get_partner(partner_id: str):
    """
    Возвращает данные конкретного партнера по ID.
    """
    try:
        data, count = supabase.table("partners").select("*").eq("id", partner_id).execute()
        if not data[1] or len(data[1]) == 0:
            raise HTTPException(status_code=404, detail="Partner not found")
        return data[1][0]
    except HTTPException:
        # Перебрасываем HTTPException без изменений
        raise 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении партнера {partner_id}: {str(e)}")

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
    """
    Возвращает список рефералов (партнеров, привлеченных данным партнером).
    """
    try:
        data, count = supabase.table("partners").select("*").eq("referrer_id", partner_id).execute()
        return data[1]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении рефералов партнера {partner_id}: {str(e)}")

# <<< НОВОЕ: Маршрут для статистики по пользователю >>>
@app.get("/deals/partner/{partner_id}")
def get_deals_for_partner(partner_id: str):
    """
    Возвращает статистику и данные для конкретного партнера.
    """
    try:
        # 1. Получаем все сделки партнера
        deals_response = supabase.table("deals").select("*").eq("partner_id", partner_id).execute()
        deals = deals_response.data if deals_response.data else []

        # 2. Получаем бонусы, которые получил партнер как реферер (уровень 1)
        bonuses_received_response = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
        bonuses_received = bonuses_received_response.data if bonuses_received_response.data else []

        # 3. Получаем список рефералов 1-го уровня
        referrals_response = supabase.table("partners").select("id").eq("referrer_id", partner_id).execute()
        referrals = [r['id'] for r in referrals_response.data] if referrals_response.data else []

        # 4. Считаем статистику
        total_deals = len(deals)
        total_commission = sum(d.get('amount', 0) for d in deals)
        total_bonuses = sum(b.get('bonus', 0) for b in bonuses_received)
        referrals_count = len(referrals)

        # 5. Формируем ответ
        result = {
            "partner_id": partner_id,
            "stats": {
                "total_deals": total_deals,
                "total_commission": total_commission,
                "total_bonuses": total_bonuses,
                "referrals_count": referrals_count
            },
            "deals": deals,
            "bonuses_received": bonuses_received
        }

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error in get_deals_for_partner: {str(e)}")
