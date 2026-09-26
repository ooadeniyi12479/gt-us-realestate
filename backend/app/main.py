from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./gtext.db")
RENTCAST_API_KEY=os.getenv("RENTCAST_API_KEY","")
RENTCAST_BASE_URL=os.getenv("RENTCAST_BASE_URL","https://api.rentcast.io/v1")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","")
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-5.6-luna")
REFRESH_HOURS=int(os.getenv("REFRESH_HOURS","6"))
STALE_HOURS=int(os.getenv("STALE_HOURS","18"))
AUTH_REQUIRED=os.getenv("AUTH_REQUIRED","true").lower()=="true"
OFFMARKET_API_URL=os.getenv("OFFMARKET_API_URL","")
OFFMARKET_API_TOKEN=os.getenv("OFFMARKET_API_TOKEN","")
SMTP_HOST=os.getenv("SMTP_HOST","")
SMTP_PORT=int(os.getenv("SMTP_PORT","587"))
SMTP_USER=os.getenv("SMTP_USER","")
SMTP_PASSWORD=os.getenv("SMTP_PASSWORD","")
SMTP_FROM=os.getenv("SMTP_FROM",SMTP_USER or "alerts@gtext.local")
SMTP_TLS=os.getenv("SMTP_TLS","true").lower()=="true"
TWILIO_ACCOUNT_SID=os.getenv("TWILIO_ACCOUNT_SID","")
TWILIO_AUTH_TOKEN=os.getenv("TWILIO_AUTH_TOKEN","")
TWILIO_FROM=os.getenv("TWILIO_FROM","")

engine=create_engine(DATABASE_URL,connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {})

def utcnow(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class Property(Base):
    __tablename__="properties"
    id:Mapped[str]=mapped_column(String,primary_key=True)
    provider_id:Mapped[str]=mapped_column(String,default="")
    address:Mapped[str]=mapped_column(String)
    city:Mapped[str]=mapped_column(String,index=True)
    state:Mapped[str]=mapped_column(String,index=True)
    zip:Mapped[str]=mapped_column(String,default="")
    property_type:Mapped[str]=mapped_column(String,default="Single Family")
    beds:Mapped[int]=mapped_column(Integer,default=0)
    baths:Mapped[float]=mapped_column(Float,default=0)
    sqft:Mapped[int]=mapped_column(Integer,default=0)
    year_built:Mapped[int]=mapped_column(Integer,default=0)
    asking_price:Mapped[float]=mapped_column(Float,default=0)
    estimated_arv:Mapped[float]=mapped_column(Float,default=0)
    estimated_rehab:Mapped[float]=mapped_column(Float,default=0)
    estimated_rent:Mapped[float]=mapped_column(Float,default=0)
    taxes_annual:Mapped[float]=mapped_column(Float,default=0)
    source:Mapped[str]=mapped_column(String,default="manual")
    market_type:Mapped[str]=mapped_column(String,default="on-market")
    status:Mapped[str]=mapped_column(String,default="active",index=True)
    days_on_market:Mapped[int]=mapped_column(Integer,default=0)
    latitude:Mapped[Optional[float]]=mapped_column(Float,nullable=True)
    longitude:Mapped[Optional[float]]=mapped_column(Float,nullable=True)
    distress_signals:Mapped[list]=mapped_column(JSON,default=list)
    agent_name:Mapped[str]=mapped_column(String,default="")
    agent_email:Mapped[str]=mapped_column(String,default="")
    agent_phone:Mapped[str]=mapped_column(String,default="")
    owner_name:Mapped[str]=mapped_column(String,default="")
    owner_email:Mapped[str]=mapped_column(String,default="")
    owner_phone:Mapped[str]=mapped_column(String,default="")
    last_seen:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    first_seen:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    saved:Mapped[bool]=mapped_column(Boolean,default=False)
    notes:Mapped[str]=mapped_column(Text,default="")

class StatusEvent(Base):
    __tablename__="status_events"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[str]=mapped_column(String,index=True)
    status:Mapped[str]=mapped_column(String)
    source:Mapped[str]=mapped_column(String)
    observed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Settings(Base):
    __tablename__="settings"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,default=1)
    min_deal_score:Mapped[int]=mapped_column(Integer,default=65)
    mao_percent:Mapped[float]=mapped_column(Float,default=.70)
    min_flip_profit:Mapped[float]=mapped_column(Float,default=40000)
    min_flip_roi:Mapped[float]=mapped_column(Float,default=12)
    min_gross_yield:Mapped[float]=mapped_column(Float,default=6)
    min_wholesale_spread:Mapped[float]=mapped_column(Float,default=10000)
    max_price:Mapped[float]=mapped_column(Float,default=1000000)
    target_states:Mapped[list]=mapped_column(JSON,default=lambda:["TX"])
    target_cities:Mapped[list]=mapped_column(JSON,default=lambda:["Prosper","Frisco","McKinney","Plano","Little Elm"])

class Investor(Base):
    __tablename__="investors"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    email:Mapped[str]=mapped_column(String,unique=True,index=True)
    name:Mapped[str]=mapped_column(String)
    company:Mapped[str]=mapped_column(String,default="")
    password_hash:Mapped[str]=mapped_column(String)
    salt:Mapped[str]=mapped_column(String)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Token(Base):
    __tablename__="auth_tokens"
    token:Mapped[str]=mapped_column(String,primary_key=True)
    investor_id:Mapped[int]=mapped_column(Integer,index=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))

class Distress(Base):
    __tablename__="distress_records"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[str]=mapped_column(String,index=True)
    provider:Mapped[str]=mapped_column(String)
    record_type:Mapped[str]=mapped_column(String,index=True)
    severity:Mapped[int]=mapped_column(Integer,default=1)
    amount:Mapped[float]=mapped_column(Float,default=0)
    owner_name:Mapped[str]=mapped_column(String,default="")
    owner_email:Mapped[str]=mapped_column(String,default="")
    owner_phone:Mapped[str]=mapped_column(String,default="")
    mailing_address:Mapped[str]=mapped_column(String,default="")
    estimated_equity_pct:Mapped[float]=mapped_column(Float,default=0)
    source_url:Mapped[str]=mapped_column(String,default="")
    verified_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    raw_payload:Mapped[dict]=mapped_column(JSON,default=dict)

class Contact(Base):
    __tablename__="crm_contacts"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[Optional[str]]=mapped_column(String,nullable=True,index=True)
    contact_type:Mapped[str]=mapped_column(String,default="seller")
    name:Mapped[str]=mapped_column(String)
    email:Mapped[str]=mapped_column(String,default="")
    phone:Mapped[str]=mapped_column(String,default="")
    status:Mapped[str]=mapped_column(String,default="new",index=True)
    source:Mapped[str]=mapped_column(String,default="manual")
    notes:Mapped[str]=mapped_column(Text,default="")
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Outreach(Base):
    __tablename__="outreach_messages"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[Optional[str]]=mapped_column(String,nullable=True)
    contact_id:Mapped[Optional[int]]=mapped_column(Integer,nullable=True)
    channel:Mapped[str]=mapped_column(String,default="email")
    recipient:Mapped[str]=mapped_column(String)
    subject:Mapped[str]=mapped_column(String,default="")
    body:Mapped[str]=mapped_column(Text)
    status:Mapped[str]=mapped_column(String,default="draft")
    consent_confirmed:Mapped[bool]=mapped_column(Boolean,default=False)
    suppressed:Mapped[bool]=mapped_column(Boolean,default=False)
    sent_at:Mapped[Optional[datetime]]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Underwriting(Base):
    __tablename__="underwriting_cases"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[str]=mapped_column(String,index=True)
    strategy:Mapped[str]=mapped_column(String,default="Buy & Hold")
    assumptions:Mapped[dict]=mapped_column(JSON,default=dict)
    results:Mapped[dict]=mapped_column(JSON,default=dict)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Offer(Base):
    __tablename__="offers"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[str]=mapped_column(String,index=True)
    investor_id:Mapped[Optional[int]]=mapped_column(Integer,nullable=True)
    offer_price:Mapped[float]=mapped_column(Float)
    earnest_money:Mapped[float]=mapped_column(Float,default=1000)
    close_days:Mapped[int]=mapped_column(Integer,default=21)
    inspection_days:Mapped[int]=mapped_column(Integer,default=7)
    financing:Mapped[str]=mapped_column(String,default="Cash")
    status:Mapped[str]=mapped_column(String,default="draft")
    recipient_name:Mapped[str]=mapped_column(String,default="")
    letter:Mapped[str]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class DealRoom(Base):
    __tablename__="deal_rooms"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    property_id:Mapped[str]=mapped_column(String,index=True)
    investor_id:Mapped[Optional[int]]=mapped_column(Integer,nullable=True)
    name:Mapped[str]=mapped_column(String)
    stage:Mapped[str]=mapped_column(String,default="underwriting",index=True)
    purchase_price:Mapped[float]=mapped_column(Float,default=0)
    projected_value:Mapped[float]=mapped_column(Float,default=0)
    invested_capital:Mapped[float]=mapped_column(Float,default=0)
    target_close:Mapped[Optional[datetime]]=mapped_column(DateTime(timezone=True),nullable=True)
    checklist:Mapped[list]=mapped_column(JSON,default=list)
    documents:Mapped[list]=mapped_column(JSON,default=list)
    notes:Mapped[str]=mapped_column(Text,default="")
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

Base.metadata.create_all(engine)

class RegisterIn(BaseModel):
    email:str; name:str; password:str=Field(min_length=8); company:str=""

class LoginIn(BaseModel):
    email:str; password:str

class BuyBoxIn(BaseModel):
    min_deal_score:int=65; mao_percent:float=.70; min_flip_profit:float=40000
    min_flip_roi:float=12; min_gross_yield:float=6; min_wholesale_spread:float=10000
    max_price:float=1000000; target_states:list[str]=["TX"]
    target_cities:list[str]=["Prosper","Frisco","McKinney","Plano","Little Elm"]

class ContactIn(BaseModel):
    property_id:Optional[str]=None; contact_type:str="seller"; name:str
    email:str=""; phone:str=""; status:str="new"; source:str="manual"; notes:str=""

class DistressIn(BaseModel):
    property_id:str; provider:str="licensed-provider"; record_type:str
    severity:int=Field(1,ge=1,le=5); amount:float=0; owner_name:str=""; owner_email:str=""
    owner_phone:str=""; mailing_address:str=""; estimated_equity_pct:float=0; source_url:str=""

class UnderwriteIn(BaseModel):
    strategy:str="Buy & Hold"; purchase_price:Optional[float]=None; rehab:Optional[float]=None
    down_payment_pct:float=20; interest_rate:float=7; loan_term_years:int=30
    closing_cost_pct:float=3; vacancy_pct:float=5; management_pct:float=8
    maintenance_pct:float=5; insurance_annual:float=1800; hoa_monthly:float=0
    utilities_monthly:float=0; holding_months:int=6; sales_cost_pct:float=7

class OfferIn(BaseModel):
    offer_price:float; earnest_money:float=1000; close_days:int=21
    inspection_days:int=7; financing:str="Cash"; recipient_name:str=""

class OutreachIn(BaseModel):
    property_id:Optional[str]=None; contact_id:Optional[int]=None; channel:str="email"
    recipient:str; subject:str=""; body:str; consent_confirmed:bool=False; suppressed:bool=False

class DealRoomIn(BaseModel):
    property_id:str; name:str=""; stage:str="underwriting"; purchase_price:float=0
    projected_value:float=0; invested_capital:float=0; target_close:Optional[datetime]=None
    checklist:list=[]; documents:list=[]; notes:str=""

app=FastAPI(title="GTEXT Real Estate Assistant API",version="3.1.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","http://localhost:8080,http://localhost:5173").split(","),allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

def password_hash(password,salt): return hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),200_000).hex()

def investor_from_token(value):
    if not value: return None
    with Session(engine) as s:
        t=s.get(Token,value)
        if not t: return None
        exp=t.expires_at if t.expires_at.tzinfo else t.expires_at.replace(tzinfo=timezone.utc)
        if exp<utcnow(): s.delete(t); s.commit(); return None
        return s.get(Investor,t.investor_id)

@app.middleware("http")
async def auth_guard(request:Request,call_next):
    public=request.url.path in {"/health","/auth/register","/auth/login","/openapi.json"} or request.url.path.startswith("/docs") or request.url.path.startswith("/redoc")
    if AUTH_REQUIRED and not public and request.method!="OPTIONS":
        header=request.headers.get("Authorization","")
        inv=investor_from_token(header[7:] if header.startswith("Bearer ") else "")
        if not inv:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401,content={"detail":"Authentication required"})
        request.state.investor_id=inv.id
    return await call_next(request)

def iid(request): return getattr(request.state,"investor_id",None)

def cfg(s):
    row=s.get(Settings,1)
    if not row: row=Settings(id=1); s.add(row); s.commit(); s.refresh(row)
    return row

def analysis(p,c):
    mao=p.estimated_arv*c.mao_percent-p.estimated_rehab
    profit=p.estimated_arv-p.asking_price-p.estimated_rehab
    invested=p.asking_price+p.estimated_rehab
    roi=profit/invested*100 if invested else 0
    gy=p.estimated_rent*12/p.asking_price*100 if p.asking_price else 0
    spread=mao-p.asking_price
    disc=(p.estimated_arv-p.asking_price)/p.estimated_arv*100 if p.estimated_arv else 0
    score=50+min(22,max(-22,disc*.85))+(12 if roi>=c.min_flip_roi else -5)+(8 if gy>=c.min_gross_yield else 0)+(6 if p.market_type=="off-market" else 0)+(4 if p.days_on_market>=45 else 0)-(18 if p.status!="active" else 0)
    strategies=[]
    if profit>=c.min_flip_profit and roi>=c.min_flip_roi: strategies.append("Fix & Flip")
    if gy>=c.min_gross_yield: strategies.append("Buy & Hold")
    if spread>=c.min_wholesale_spread: strategies.append("Wholesale")
    risks=list(p.distress_signals or [])
    if p.asking_price and p.asking_price>mao: risks.append("Asking price exceeds configured MAO")
    score=round(max(0,min(100,score)))
    return {"mao":round(mao,2),"flip_profit":round(profit,2),"roi":round(roi,1),"gross_yield":round(gy,1),"wholesale_spread":round(spread,2),"score":score,"strategies":strategies or ["Further Analysis"],"risks":risks,"qualified":p.status=="active" and score>=c.min_deal_score and p.asking_price<=c.max_price}

def prop_json(p,c):
    return {"id":p.id,"address":p.address,"city":p.city,"state":p.state,"zip":p.zip,"property_type":p.property_type,"beds":p.beds,"baths":p.baths,"sqft":p.sqft,"year_built":p.year_built,"asking_price":p.asking_price,"estimated_arv":p.estimated_arv,"estimated_rehab":p.estimated_rehab,"estimated_rent":p.estimated_rent,"taxes_annual":p.taxes_annual,"source":p.source,"market_type":p.market_type,"status":p.status,"days_on_market":p.days_on_market,"latitude":p.latitude,"longitude":p.longitude,"distress_signals":p.distress_signals or [],"agent_name":p.agent_name,"agent_email":p.agent_email,"agent_phone":p.agent_phone,"owner_name":p.owner_name,"owner_email":p.owner_email,"owner_phone":p.owner_phone,"last_seen":p.last_seen.isoformat(),"first_seen":p.first_seen.isoformat(),"saved":p.saved,"notes":p.notes,"analysis":analysis(p,c)}

def seed():
    with Session(engine) as s:
        cfg(s)
        if s.scalar(select(Property.id).limit(1)): return
        now=utcnow()
        demo=[
            dict(id="TX-001",address="1840 Prairie View Dr",city="Prosper",state="TX",zip="75078",beds=4,baths=3,sqft=2780,year_built=2018,asking_price=515000,estimated_arv=635000,estimated_rehab=42000,estimated_rent=3600,taxes_annual=9800,source="Demo MLS Adapter",market_type="on-market",status="active",days_on_market=38,distress_signals=["Longer-than-target DOM"],latitude=33.2362,longitude=-96.8011),
            dict(id="TX-002",address="721 Oak Ridge Ln",city="McKinney",state="TX",zip="75071",beds=3,baths=2,sqft=2050,year_built=1998,asking_price=329000,estimated_arv=455000,estimated_rehab=51000,estimated_rent=2850,taxes_annual=6600,source="Demo Public Records Adapter",market_type="off-market",status="active",days_on_market=0,distress_signals=["Tax delinquency signal","High estimated equity"],latitude=33.2167,longitude=-96.6580,owner_name="Demo Owner"),
            dict(id="TX-003",address="3908 Legacy Creek Ct",city="Plano",state="TX",zip="75024",beds=4,baths=3.5,sqft=3210,year_built=2006,asking_price=690000,estimated_arv=760000,estimated_rehab=25000,estimated_rent=4200,taxes_annual=11800,source="Demo MLS Adapter",market_type="on-market",status="active",days_on_market=14,distress_signals=[],latitude=33.0774,longitude=-96.8085)
        ]
        for d in demo:
            p=Property(**d,first_seen=now,last_seen=now); s.add(p); s.add(StatusEvent(property_id=p.id,status=p.status,source=p.source,observed_at=now))
        s.commit()
seed()

@app.get("/health")
def health(): return {"ok":True,"version":"3.1.0","refresh_hours":REFRESH_HOURS,"auth_required":AUTH_REQUIRED,"providers":{"rentcast":bool(RENTCAST_API_KEY),"offmarket":bool(OFFMARKET_API_URL and OFFMARKET_API_TOKEN)}}

@app.post("/auth/register")
def register(data:RegisterIn):
    with Session(engine) as s:
        if s.scalar(select(Investor.id).where(Investor.email==data.email.lower())): raise HTTPException(409,"Email already registered")
        salt=secrets.token_hex(16); inv=Investor(email=data.email.lower(),name=data.name,company=data.company,password_hash=password_hash(data.password,salt),salt=salt)
        s.add(inv); s.commit(); s.refresh(inv); token=secrets.token_urlsafe(32); s.add(Token(token=token,investor_id=inv.id,expires_at=utcnow()+timedelta(days=30))); s.commit()
        return {"token":token,"investor":{"id":inv.id,"email":inv.email,"name":inv.name,"company":inv.company}}

@app.post("/auth/login")
def login(data:LoginIn):
    with Session(engine) as s:
        inv=s.scalar(select(Investor).where(Investor.email==data.email.lower()))
        if not inv or not hmac.compare_digest(inv.password_hash,password_hash(data.password,inv.salt)): raise HTTPException(401,"Invalid credentials")
        token=secrets.token_urlsafe(32); s.add(Token(token=token,investor_id=inv.id,expires_at=utcnow()+timedelta(days=30))); s.commit()
        return {"token":token,"investor":{"id":inv.id,"email":inv.email,"name":inv.name,"company":inv.company}}

@app.get("/auth/me")
def me(request:Request):
    with Session(engine) as s:
        inv=s.get(Investor,iid(request)) if iid(request) else None
        return {"id":inv.id,"email":inv.email,"name":inv.name,"company":inv.company} if inv else {"anonymous":True}

@app.get("/settings")
def get_buy_box():
    with Session(engine) as s:
        c=cfg(s); return {k:getattr(c,k) for k in ["min_deal_score","mao_percent","min_flip_profit","min_flip_roi","min_gross_yield","min_wholesale_spread","max_price","target_states","target_cities"]}

@app.put("/settings")
def put_buy_box(data:BuyBoxIn):
    with Session(engine) as s:
        c=cfg(s)
        for k,v in data.model_dump().items(): setattr(c,k,v)
        s.commit(); return {"ok":True}

@app.get("/properties")
def properties(q:str="",market_type:str="all",status:str="active",min_score:int=0):
    with Session(engine) as s:
        c=cfg(s); out=[]
        for p in s.scalars(select(Property)).all():
            if q and q.lower() not in f"{p.address} {p.city} {p.state} {p.zip}".lower(): continue
            if market_type!="all" and p.market_type!=market_type: continue
            if status!="all" and p.status!=status: continue
            item=prop_json(p,c)
            if item["analysis"]["score"]>=min_score: out.append(item)
        return sorted(out,key=lambda x:x["analysis"]["score"],reverse=True)

@app.get("/properties/map")
def property_map(north:float=90,south:float=-90,east:float=180,west:float=-180,min_score:int=0):
    return [x for x in properties(status="active",min_score=min_score) if x["latitude"] is not None and x["longitude"] is not None and south<=x["latitude"]<=north and west<=x["longitude"]<=east]

@app.get("/properties/{property_id}")
def property_detail(property_id:str):
    with Session(engine) as s:
        p=s.get(Property,property_id)
        if not p: raise HTTPException(404,"Property not found")
        item=prop_json(p,cfg(s)); rows=s.scalars(select(StatusEvent).where(StatusEvent.property_id==property_id).order_by(StatusEvent.observed_at.desc())).all()
        item["status_history"]=[{"status":r.status,"source":r.source,"observed_at":r.observed_at.isoformat()} for r in rows]; return item

@app.patch("/properties/{property_id}/save")
def save_property(property_id:str):
    with Session(engine) as s:
        p=s.get(Property,property_id)
        if not p: raise HTTPException(404,"Property not found")
        p.saved=not p.saved; s.commit(); return {"saved":p.saved}

@app.post("/properties/import")
def import_properties(rows:list[dict]):
    allowed={"id","provider_id","address","city","state","zip","property_type","beds","baths","sqft","year_built","asking_price","estimated_arv","estimated_rehab","estimated_rent","taxes_annual","source","market_type","status","days_on_market","latitude","longitude","distress_signals","agent_name","agent_email","agent_phone","owner_name","owner_email","owner_phone","saved","notes"}
    inserted=0; updated=0; errors=[]; now=utcnow()
    with Session(engine) as s:
        for i,row in enumerate(rows):
            try:
                data={k:v for k,v in row.items() if k in allowed}
                pid=str(data.get("id") or "").strip()
                if not pid or not data.get("address"):
                    raise ValueError("id and address are required")
                data["id"]=pid
                p=s.get(Property,pid)
                if p:
                    old=p.status
                    for k,v in data.items():
                        if k!="id": setattr(p,k,v)
                    p.last_seen=now; updated+=1
                    if old!=p.status: s.add(StatusEvent(property_id=p.id,status=p.status,source=p.source,observed_at=now))
                else:
                    p=Property(**data,first_seen=now,last_seen=now)
                    s.add(p); s.add(StatusEvent(property_id=p.id,status=p.status,source=p.source,observed_at=now)); inserted+=1
            except Exception as e:
                errors.append({"row":i+1,"error":str(e)})
        s.commit()
    return {"inserted":inserted,"updated":updated,"errors":errors,"total":inserted+updated}

def rentcast_get(path,params):
    if not RENTCAST_API_KEY: return []
    with httpx.Client(timeout=30) as c:
        r=c.get(f"{RENTCAST_BASE_URL}{path}",params=params,headers={"X-Api-Key":RENTCAST_API_KEY,"Accept":"application/json"}); r.raise_for_status(); return r.json()

def normalize_listing(x):
    pid=str(x.get("id") or x.get("mlsNumber") or x.get("formattedAddress") or secrets.token_hex(8)); price=float(x.get("price") or x.get("listedPrice") or 0)
    raw=str(x.get("status") or "active").lower().replace(" ","-"); status="active" if raw in {"active","for-sale","forsale"} else raw
    return dict(id=f"rentcast:{pid}",provider_id=pid,address=x.get("addressLine1") or x.get("formattedAddress") or "Unknown address",city=x.get("city") or "",state=x.get("state") or "",zip=str(x.get("zipCode") or ""),property_type=x.get("propertyType") or "Residential",beds=int(x.get("bedrooms") or 0),baths=float(x.get("bathrooms") or 0),sqft=int(x.get("squareFootage") or 0),year_built=int(x.get("yearBuilt") or 0),asking_price=price,estimated_arv=float(x.get("estimatedValue") or price),estimated_rehab=0,estimated_rent=float(x.get("estimatedRent") or 0),taxes_annual=float(x.get("propertyTaxes") or 0),source="RentCast",market_type="on-market",status=status,days_on_market=int(x.get("daysOnMarket") or 0),latitude=x.get("latitude"),longitude=x.get("longitude"),distress_signals=[])

def refresh_live_feeds():
    result={"enabled":bool(RENTCAST_API_KEY),"fetched":0,"inserted":0,"updated":0,"stale_reconciled":0,"errors":[]}
    with Session(engine) as s:
        c=cfg(s); now=utcnow()
        if RENTCAST_API_KEY:
            for state in c.target_states:
                for city in c.target_cities:
                    try:
                        payload=rentcast_get("/listings/sale",{"city":city,"state":state,"limit":150}); rows=payload if isinstance(payload,list) else payload.get("data",[])
                        for raw in rows:
                            d=normalize_listing(raw); p=s.get(Property,d["id"])
                            if not p:
                                p=Property(**d,first_seen=now,last_seen=now); s.add(p); s.add(StatusEvent(property_id=p.id,status=p.status,source=p.source,observed_at=now)); result["inserted"]+=1
                            else:
                                old=p.status
                                for k,v in d.items():
                                    if k!="id": setattr(p,k,v)
                                p.last_seen=now; result["updated"]+=1
                                if old!=p.status: s.add(StatusEvent(property_id=p.id,status=p.status,source=p.source,observed_at=now))
                            result["fetched"]+=1
                    except Exception as e: result["errors"].append(f"{city}, {state}: {str(e)[:160]}")
            cutoff=now-timedelta(hours=STALE_HOURS)
            for p in s.scalars(select(Property).where(Property.source=="RentCast",Property.status=="active")).all():
                seen=p.last_seen if p.last_seen.tzinfo else p.last_seen.replace(tzinfo=timezone.utc)
                if seen<cutoff:
                    p.status="unconfirmed-off-market"; s.add(StatusEvent(property_id=p.id,status=p.status,source=p.source,observed_at=now)); result["stale_reconciled"]+=1
        s.commit()
    return result

@app.post("/refresh")
def refresh():
    out={"listings":refresh_live_feeds()}
    if OFFMARKET_API_URL and OFFMARKET_API_TOKEN: out["distress"]=sync_distress()
    return out

@app.get("/properties/{property_id}/comps")
def comps(property_id:str,radius:float=Query(3,ge=.5,le=20),days:int=Query(180,ge=30,le=730)):
    with Session(engine) as s:
        p=s.get(Property,property_id)
        if not p: raise HTTPException(404,"Property not found")
        rows=[]
        if RENTCAST_API_KEY:
            try:
                params={"radius":radius,"saleDateRange":days,"limit":25}
                if p.latitude is not None and p.longitude is not None: params.update({"latitude":p.latitude,"longitude":p.longitude})
                else: params["address"]=f"{p.address}, {p.city}, {p.state} {p.zip}"
                payload=rentcast_get("/properties",params); source=payload if isinstance(payload,list) else payload.get("data",[])
                for r in source:
                    price=float(r.get("lastSalePrice") or r.get("price") or 0); sqft=int(r.get("squareFootage") or 0)
                    if price: rows.append({"address":r.get("formattedAddress") or r.get("addressLine1") or "","sale_price":price,"sale_date":r.get("lastSaleDate"),"sqft":sqft,"price_per_sqft":round(price/sqft,2) if sqft else 0})
            except Exception: rows=[]
        if not rows:
            rows=[{"address":f"Nearby comp {i+1}","sale_price":round(p.estimated_arv*(.94+i*.03),2),"sale_date":(utcnow()-timedelta(days=45+i*30)).date().isoformat(),"sqft":max(p.sqft+(-100+i*80),500),"price_per_sqft":round((p.estimated_arv*(.94+i*.03))/max(p.sqft+(-100+i*80),500),2)} for i in range(3)]
        prices=[r["sale_price"] for r in rows]; ppsf=[r["price_per_sqft"] for r in rows if r["price_per_sqft"]]
        return {"property_id":property_id,"count":len(rows),"average_sale_price":round(sum(prices)/len(prices),2),"average_price_per_sqft":round(sum(ppsf)/len(ppsf),2) if ppsf else 0,"comps":rows}

@app.post("/properties/{property_id}/memo")
def memo(property_id:str):
    with Session(engine) as s:
        p=s.get(Property,property_id)
        if not p: raise HTTPException(404,"Property not found")
        a=analysis(p,cfg(s))
        fallback=f"""DEAL SNAPSHOT
{p.address}, {p.city}, {p.state} {p.zip}
Asking: {p.asking_price:,.0f} USD | ARV: {p.estimated_arv:,.0f} USD | Rehab: {p.estimated_rehab:,.0f} USD
Deal score: {a['score']}/100 | MAO: {a['mao']:,.0f} USD

STRATEGY FIT
{', '.join(a['strategies'])}

RISKS
{'; '.join(a['risks']) or 'No major rule-based flags from available fields.'}

NEXT DILIGENCE
Verify title and liens, property condition, repair scope, taxes and HOA, insurance, zoning, rents, sold comps and current seller/listing status before making a binding offer."""
        if not OPENAI_API_KEY:
            return {"property_id":property_id,"model":"rules","content":fallback}
        prompt=("Act as a disciplined U.S. real-estate acquisition analyst. Produce a concise investment memo with sections: Deal Snapshot, "
                "Market and Comps, Strategy Fit, Risks, Negotiation Angle, and Next Due-Diligence Steps. Do not invent facts. "
                f"Property: {p.address}, {p.city}, {p.state} {p.zip}; asking {p.asking_price}; ARV {p.estimated_arv}; rehab {p.estimated_rehab}; "
                f"rent {p.estimated_rent}; score {a['score']}; MAO {a['mao']}; strategies {a['strategies']}; risks {a['risks']}.")
        try:
            with httpx.Client(timeout=45) as client:
                r=client.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},json={"model":OPENAI_MODEL,"input":prompt})
                r.raise_for_status(); payload=r.json()
            text=payload.get("output_text")
            if not text:
                parts=[]
                for item in payload.get("output",[]):
                    for part in item.get("content",[]):
                        if part.get("type")=="output_text" and part.get("text"): parts.append(part["text"])
                text="\n".join(parts)
            return {"property_id":property_id,"model":OPENAI_MODEL,"content":text or fallback}
        except Exception:
            return {"property_id":property_id,"model":"rules-fallback","content":fallback}

@app.get("/distress/{property_id}")
def distress_records(property_id:str):
    with Session(engine) as s:
        rows=s.scalars(select(Distress).where(Distress.property_id==property_id).order_by(Distress.verified_at.desc())).all()
        return [{"id":r.id,"provider":r.provider,"record_type":r.record_type,"severity":r.severity,"amount":r.amount,"owner_name":r.owner_name,"owner_email":r.owner_email,"owner_phone":r.owner_phone,"mailing_address":r.mailing_address,"estimated_equity_pct":r.estimated_equity_pct,"source_url":r.source_url,"verified_at":r.verified_at.isoformat()} for r in rows]

@app.post("/distress/import")
def distress_import(data:DistressIn):
    with Session(engine) as s:
        r=Distress(**data.model_dump(),verified_at=utcnow(),raw_payload=data.model_dump()); s.add(r); s.commit(); s.refresh(r); return {"id":r.id,"ok":True}

def sync_distress():
    if not (OFFMARKET_API_URL and OFFMARKET_API_TOKEN): return {"enabled":False,"imported":0}
    with httpx.Client(timeout=45) as c:
        r=c.get(OFFMARKET_API_URL,headers={"Authorization":f"Bearer {OFFMARKET_API_TOKEN}"}); r.raise_for_status(); payload=r.json()
    rows=payload if isinstance(payload,list) else payload.get("records",[]); count=0
    with Session(engine) as s:
        for x in rows:
            pid=str(x.get("property_id") or x.get("propertyId") or "")
            if not pid: continue
            s.add(Distress(property_id=pid,provider=x.get("provider","licensed-provider"),record_type=x.get("record_type") or x.get("recordType") or "distress",severity=int(x.get("severity") or 1),amount=float(x.get("amount") or 0),owner_name=x.get("ownerName") or x.get("owner_name") or "",owner_email=x.get("ownerEmail") or x.get("owner_email") or "",owner_phone=x.get("ownerPhone") or x.get("owner_phone") or "",mailing_address=x.get("mailingAddress") or "",estimated_equity_pct=float(x.get("equityPct") or 0),source_url=x.get("source_url") or "",verified_at=utcnow(),raw_payload=x)); count+=1
        s.commit()
    return {"enabled":True,"imported":count}

@app.post("/distress/sync")
def distress_sync(): return sync_distress()

def mortgage(principal,rate,years):
    if principal<=0:return 0
    if rate<=0:return principal/(years*12)
    r=rate/100/12; n=years*12
    return principal*(r*(1+r)**n)/((1+r)**n-1)

@app.post("/properties/{property_id}/underwrite")
def underwrite(property_id:str,data:UnderwriteIn):
    with Session(engine) as s:
        p=s.get(Property,property_id)
        if not p: raise HTTPException(404,"Property not found")
        purchase=data.purchase_price if data.purchase_price is not None else p.asking_price; rehab=data.rehab if data.rehab is not None else p.estimated_rehab
        down=purchase*data.down_payment_pct/100; loan=max(purchase-down,0); debt=mortgage(loan,data.interest_rate,data.loan_term_years)
        gross=p.estimated_rent; vacancy=gross*data.vacancy_pct/100; mgmt=gross*data.management_pct/100; maint=gross*data.maintenance_pct/100; tax=p.taxes_annual/12; ins=data.insurance_annual/12
        noi=gross-vacancy-mgmt-maint-tax-ins-data.hoa_monthly-data.utilities_monthly; cashflow=noi-debt; closing=purchase*data.closing_cost_pct/100; cash_required=down+closing+rehab
        cap=noi*12/purchase*100 if purchase else 0; coc=cashflow*12/cash_required*100 if cash_required else 0; dscr=noi/debt if debt else 0
        sale_cost=p.estimated_arv*data.sales_cost_pct/100; holding=max(0,debt+tax+ins+data.hoa_monthly+data.utilities_monthly)*data.holding_months; flip=p.estimated_arv-purchase-rehab-closing-sale_cost-holding
        result={"loan_amount":round(loan,2),"monthly_pi":round(debt,2),"cash_required":round(cash_required,2),"monthly_noi":round(noi,2),"monthly_cash_flow":round(cashflow,2),"annual_cash_flow":round(cashflow*12,2),"cap_rate_pct":round(cap,2),"cash_on_cash_pct":round(coc,2),"dscr":round(dscr,2),"flip_net_profit":round(flip,2),"break_even_occupancy_pct":round(((mgmt+maint+tax+ins+data.hoa_monthly+data.utilities_monthly+debt)/gross*100),1) if gross else 0}
        row=Underwriting(property_id=property_id,strategy=data.strategy,assumptions=data.model_dump(),results=result); s.add(row); s.commit(); s.refresh(row); return {"id":row.id,"strategy":row.strategy,"results":result}

@app.get("/properties/{property_id}/underwriting")
def underwriting_history(property_id:str):
    with Session(engine) as s:
        rows=s.scalars(select(Underwriting).where(Underwriting.property_id==property_id).order_by(Underwriting.created_at.desc()).limit(20)).all()
        return [{"id":r.id,"strategy":r.strategy,"results":r.results,"created_at":r.created_at.isoformat()} for r in rows]

@app.post("/crm/contacts")
def create_contact(data:ContactIn):
    with Session(engine) as s:
        r=Contact(**data.model_dump(),updated_at=utcnow()); s.add(r); s.commit(); s.refresh(r); return {"id":r.id,"ok":True}

@app.get("/crm/contacts")
def contacts():
    with Session(engine) as s:
        return [{"id":r.id,"property_id":r.property_id,"contact_type":r.contact_type,"name":r.name,"email":r.email,"phone":r.phone,"status":r.status,"source":r.source,"notes":r.notes} for r in s.scalars(select(Contact).order_by(Contact.updated_at.desc())).all()]

@app.patch("/crm/contacts/{contact_id}")
def update_contact(contact_id:int,status:str):
    with Session(engine) as s:
        r=s.get(Contact,contact_id)
        if not r: raise HTTPException(404,"Contact not found")
        r.status=status; r.updated_at=utcnow(); s.commit(); return {"ok":True}

@app.post("/properties/{property_id}/offers")
def offer_create(property_id:str,data:OfferIn,request:Request):
    with Session(engine) as s:
        p=s.get(Property,property_id)
        if not p: raise HTTPException(404,"Property not found")
        inv=s.get(Investor,iid(request)) if iid(request) else None; buyer=(inv.company or inv.name) if inv else "GTEXT Investor"; recipient=data.recipient_name or p.owner_name or p.agent_name or "Property Owner / Listing Representative"
        letter=f"""LETTER OF INTENT — NON-BINDING

Property: {p.address}, {p.city}, {p.state} {p.zip}
To: {recipient}

{buyer} is interested in acquiring the property for {data.offer_price:,.0f} USD, subject to satisfactory due diligence, clear and marketable title, mutually acceptable purchase documentation, and any required financing approval.

Proposed terms:
- Purchase price: {data.offer_price:,.0f} USD
- Earnest money: {data.earnest_money:,.0f} USD
- Financing: {data.financing}
- Inspection period: {data.inspection_days} days
- Target closing: {data.close_days} days after executed contract

This letter is for discussion purposes only and is not intended to create a binding purchase agreement or legal obligation."""
        r=Offer(property_id=property_id,investor_id=iid(request),offer_price=data.offer_price,earnest_money=data.earnest_money,close_days=data.close_days,inspection_days=data.inspection_days,financing=data.financing,status="draft",recipient_name=recipient,letter=letter); s.add(r); s.commit(); s.refresh(r); return {"id":r.id,"status":r.status,"letter":r.letter}

@app.get("/offers")
def offers():
    with Session(engine) as s:
        return [{"id":r.id,"property_id":r.property_id,"offer_price":r.offer_price,"status":r.status,"financing":r.financing,"recipient_name":r.recipient_name,"letter":r.letter,"created_at":r.created_at.isoformat()} for r in s.scalars(select(Offer).order_by(Offer.created_at.desc())).all()]

@app.patch("/offers/{offer_id}/status")
def offer_status(offer_id:int,status:str):
    if status not in {"draft","sent","countered","accepted","rejected","expired","withdrawn"}: raise HTTPException(400,"Invalid offer status")
    with Session(engine) as s:
        r=s.get(Offer,offer_id)
        if not r: raise HTTPException(404,"Offer not found")
        r.status=status; s.commit(); return {"ok":True,"status":status}

def send_email(to,subject,body):
    if not (SMTP_HOST and to): return False
    msg=EmailMessage(); msg["From"]=SMTP_FROM; msg["To"]=to; msg["Subject"]=subject; msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=20) as server:
            if SMTP_TLS: server.starttls()
            if SMTP_USER: server.login(SMTP_USER,SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:return False

def send_sms(to,body):
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM): return False
    url=f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    with httpx.Client(timeout=20) as c:
        r=c.post(url,data={"To":to,"From":TWILIO_FROM,"Body":body},auth=(TWILIO_ACCOUNT_SID,TWILIO_AUTH_TOKEN)); r.raise_for_status()
    return True

@app.post("/outreach")
def outreach_create(data:OutreachIn):
    if data.suppressed: raise HTTPException(400,"Recipient is suppressed")
    with Session(engine) as s:
        r=Outreach(**data.model_dump(),status="draft",created_at=utcnow()); s.add(r); s.commit(); s.refresh(r); return {"id":r.id,"status":r.status,"compliance":"Delivery requires consent_confirmed true and a configured provider."}

@app.post("/outreach/{message_id}/send")
def outreach_send(message_id:int):
    with Session(engine) as s:
        r=s.get(Outreach,message_id)
        if not r: raise HTTPException(404,"Message not found")
        if r.suppressed: raise HTTPException(400,"Recipient is suppressed")
        if not r.consent_confirmed: raise HTTPException(400,"Consent or permission has not been confirmed")
        delivered=send_email(r.recipient,r.subject or "Property inquiry",r.body) if r.channel=="email" else send_sms(r.recipient,r.body) if r.channel=="sms" else False
        if not delivered: raise HTTPException(503,"Delivery provider is not configured")
        r.status="sent"; r.sent_at=utcnow(); s.commit(); return {"ok":True,"status":"sent"}

@app.get("/outreach")
def outreach_list():
    with Session(engine) as s:
        return [{"id":r.id,"property_id":r.property_id,"contact_id":r.contact_id,"channel":r.channel,"recipient":r.recipient,"subject":r.subject,"body":r.body,"status":r.status,"consent_confirmed":r.consent_confirmed,"sent_at":r.sent_at.isoformat() if r.sent_at else None} for r in s.scalars(select(Outreach).order_by(Outreach.created_at.desc()).limit(100)).all()]

@app.get("/pipeline/analytics")
def pipeline():
    with Session(engine) as s:
        cs=s.scalars(select(Contact)).all(); os_=s.scalars(select(Offer)).all(); rs=s.scalars(select(DealRoom)).all(); ms=s.scalars(select(Outreach)).all()
        def count(rows,attr):
            out={}
            for r in rows: out[getattr(r,attr)]=out.get(getattr(r,attr),0)+1
            return out
        won=sum(1 for o in os_ if o.status=="accepted")
        return {"contacts_total":len(cs),"contact_stages":count(cs,"status"),"offers_total":len(os_),"offer_statuses":count(os_,"status"),"deal_room_stages":count(rs,"stage"),"outreach_sent":sum(1 for m in ms if m.status=="sent"),"accepted_offers":won,"offer_acceptance_rate_pct":round(won/len(os_)*100,1) if os_ else 0}

@app.post("/deal-rooms")
def deal_room_create(data:DealRoomIn,request:Request):
    with Session(engine) as s:
        p=s.get(Property,data.property_id)
        if not p: raise HTTPException(404,"Property not found")
        checklist=data.checklist or [{"item":"Title and lien review","done":False},{"item":"Inspection","done":False},{"item":"Financing or proof of funds","done":False},{"item":"Insurance quote","done":False},{"item":"Closing instructions","done":False}]
        r=DealRoom(property_id=p.id,investor_id=iid(request),name=data.name or p.address,stage=data.stage,purchase_price=data.purchase_price or p.asking_price,projected_value=data.projected_value or p.estimated_arv,invested_capital=data.invested_capital,target_close=data.target_close,checklist=checklist,documents=data.documents,notes=data.notes,updated_at=utcnow()); s.add(r); s.commit(); s.refresh(r); return {"id":r.id,"ok":True}

@app.get("/deal-rooms")
def deal_rooms():
    with Session(engine) as s:
        return [{"id":r.id,"property_id":r.property_id,"name":r.name,"stage":r.stage,"purchase_price":r.purchase_price,"projected_value":r.projected_value,"invested_capital":r.invested_capital,"target_close":r.target_close.isoformat() if r.target_close else None,"checklist":r.checklist or [],"documents":r.documents or [],"notes":r.notes} for r in s.scalars(select(DealRoom).order_by(DealRoom.updated_at.desc())).all()]

@app.patch("/deal-rooms/{room_id}")
def deal_room_update(room_id:int,stage:Optional[str]=None,notes:Optional[str]=None):
    with Session(engine) as s:
        r=s.get(DealRoom,room_id)
        if not r: raise HTTPException(404,"Deal room not found")
        if stage is not None:r.stage=stage
        if notes is not None:r.notes=notes
        r.updated_at=utcnow(); s.commit(); return {"ok":True}

@app.get("/portfolio")
def portfolio():
    with Session(engine) as s:
        rows=s.scalars(select(DealRoom)).all(); active=[r for r in rows if r.stage not in {"closed","lost","sold"}]; closed=[r for r in rows if r.stage=="closed"]; basis=sum(r.purchase_price for r in closed); value=sum(r.projected_value for r in closed)
        return {"active_deals":len(active),"closed_deals":len(closed),"portfolio_purchase_basis":round(basis,2),"portfolio_projected_value":round(value,2),"projected_equity":round(value-basis,2),"rooms":[{"id":r.id,"property_id":r.property_id,"name":r.name,"stage":r.stage,"purchase_price":r.purchase_price,"projected_value":r.projected_value} for r in rows]}

def scheduled_refresh():
    result={"listings":refresh_live_feeds()}
    if OFFMARKET_API_URL and OFFMARKET_API_TOKEN:
        try:result["distress"]=sync_distress()
        except Exception as e:result["distress"]={"enabled":True,"error":str(e)}
    return result

scheduler=BackgroundScheduler(timezone="UTC")
scheduler.add_job(scheduled_refresh,"interval",hours=REFRESH_HOURS,id="property-refresh",replace_existing=True,max_instances=1)
scheduler.start()


class AlertRule(Base):
    __tablename__="alert_rules"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    name:Mapped[str]=mapped_column(String)
    email:Mapped[str]=mapped_column(String,default="")
    min_score:Mapped[int]=mapped_column(Integer,default=75)
    max_price:Mapped[float]=mapped_column(Float,default=1000000)
    city:Mapped[str]=mapped_column(String,default="")
    strategy:Mapped[str]=mapped_column(String,default="")
    enabled:Mapped[bool]=mapped_column(Boolean,default=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class AlertEvent(Base):
    __tablename__="alert_events"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    rule_id:Mapped[int]=mapped_column(Integer,index=True)
    property_id:Mapped[str]=mapped_column(String,index=True)
    message:Mapped[str]=mapped_column(Text)
    delivered:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

Base.metadata.create_all(engine)

class AlertIn(BaseModel):
    name:str
    email:str=""
    min_score:int=75
    max_price:float=1000000
    city:str=""
    strategy:str=""
    enabled:bool=True

@app.get("/dashboard")
def dashboard():
    with Session(engine) as s:
        c=cfg(s); rows=s.scalars(select(Property)).all()
        active=[p for p in rows if p.status=="active"]
        return {"active":len(active),"qualified":sum(1 for p in active if analysis(p,c)["qualified"]),"off_market":sum(1 for p in active if p.market_type=="off-market"),"saved":sum(1 for p in rows if p.saved)}

@app.get("/providers")
def providers():
    return [
        {"id":"rentcast","name":"RentCast","enabled":bool(RENTCAST_API_KEY)},
        {"id":"offmarket","name":"Distressed seller feed","enabled":bool(OFFMARKET_API_URL and OFFMARKET_API_TOKEN)},
        {"id":"openai","name":"OpenAI property memos","enabled":bool(OPENAI_API_KEY)}
    ]

@app.post("/auth/logout")
def logout(request:Request):
    header=request.headers.get("Authorization","")
    value=header[7:] if header.startswith("Bearer ") else ""
    if value:
        with Session(engine) as s:
            t=s.get(Token,value)
            if t: s.delete(t); s.commit()
    return {"ok":True}

@app.post("/alerts/rules")
def create_alert(data:AlertIn):
    with Session(engine) as s:
        r=AlertRule(**data.model_dump()); s.add(r); s.commit(); s.refresh(r)
        return {"id":r.id,"ok":True}

@app.get("/alerts/rules")
def list_alerts():
    with Session(engine) as s:
        rows=s.scalars(select(AlertRule).order_by(AlertRule.created_at.desc())).all()
        return [{"id":r.id,"name":r.name,"email":r.email,"min_score":r.min_score,"max_price":r.max_price,"city":r.city,"strategy":r.strategy,"enabled":r.enabled} for r in rows]

@app.get("/alerts/events")
def alert_events():
    with Session(engine) as s:
        rows=s.scalars(select(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(100)).all()
        return [{"id":r.id,"rule_id":r.rule_id,"property_id":r.property_id,"message":r.message,"delivered":r.delivered,"created_at":r.created_at.isoformat()} for r in rows]

@app.post("/alerts/evaluate")
def evaluate_alerts():
    created=0
    with Session(engine) as s:
        c=cfg(s); rules=s.scalars(select(AlertRule).where(AlertRule.enabled==True)).all(); props=s.scalars(select(Property).where(Property.status=="active")).all()
        for rule in rules:
            for p in props:
                a=analysis(p,c)
                if a["score"]<rule.min_score or p.asking_price>rule.max_price: continue
                if rule.city and p.city.lower()!=rule.city.lower(): continue
                if rule.strategy and rule.strategy not in a["strategies"]: continue
                existing=s.scalar(select(AlertEvent.id).where(AlertEvent.rule_id==rule.id,AlertEvent.property_id==p.id))
                if existing: continue
                msg=f"{p.address}, {p.city}, {p.state} scored {a['score']}/100 at {p.asking_price:,.0f} USD; MAO {a['mao']:,.0f} USD."
                delivered=send_email(rule.email,"GTEXT qualifying property lead",msg) if rule.email else False
                s.add(AlertEvent(rule_id=rule.id,property_id=p.id,message=msg,delivered=delivered)); created+=1
        s.commit()
    return {"created":created}

