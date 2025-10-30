from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
import os

app = FastAPI()

# Укажите URL и ключ вашего проекта Supabase (без пробелов!)
SUPABASE_URL = "https://bwvnxtfilluwnhrgsrvy.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ3dm54dGZpbGx1d25ocmdzcnZ5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE4MTM4MTUsImV4cCI6MjA3NzM4OTgxNX0.SMfrGxuZgTodskhmdCHUl4GyAsB_XvaeWInNcrn3Bzw"

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
    data, count = supabase.table("deals").insert(deal.dict()).execute()
    return data

@app.get("/bonuses/{partner_id}")
def get_bonuses(partner_id: str):
    data, count = supabase.table("bonuses").select("*").eq("referrer_id", partner_id).execute()
    return data[1]

@app.get("/partner/{partner_id}")
def get_partner(partner_id: str):
    data, count = supabase.table("partners").select("*").eq("id", partner_id).execute()
    if not data[1]:
        raise HTTPException(status_code=404, detail="Partner not found")
    return data[1][0]

@app.get("/referrals/{partner_id}")
def get_referrals(partner_id: str):
    data, count = supabase.table("partners").select("*").eq("referrer_id", partner_id).execute()
    return data[1]