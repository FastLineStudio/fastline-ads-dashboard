import streamlit as st
import os
import pandas as pd
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.user import User
from facebook_business.adobjects.campaign import Campaign

st.set_page_config(page_title="FastLine Ads Dashboard", page_icon="📊", layout="wide")

ACCESS_TOKEN = st.secrets.get("META_ACCESS_TOKEN", os.getenv("META_ACCESS_TOKEN", ""))

STATUS_MAP = {1:"ACTIVE",2:"DISABLED",3:"UNSETTLED",7:"PENDING_RISK_REVIEW",
              9:"IN_GRACE_PERIOD",100:"PENDING_CLOSURE",101:"CLOSED"}

def fmt(val, sym="zł"):
    try: return f"{sym}{float(val):,.2f}"
    except: return "-"

def num(val):
    try: return f"{int(float(val)):,}"
    except: return "-"

def pct(val):
    try: return f"{float(val):.2f}%"
    except: return "-"

def get_leads(actions):
    if not actions: return 0
    for a in actions:
        if a.get("action_type") in ("lead", "onsite_conversion.lead_grouped"):
            return int(float(a.get("value", 0)))
    for a in actions:
        if a.get("action_type") == "onsite_conversion.messaging_conversation_started_7d":
            return int(float(a.get("value", 0)))
    return 0

def fmt_budget(c):
    db = c.get("daily_budget")
    lb = c.get("lifetime_budget")
    if db and int(db) > 0:
        return f"zł{int(db)/100:,.0f}/день"
    elif lb and int(lb) > 0:
        return f"zł{int(lb)/100:,.0f} (lifetime)"
    return "-"

@st.cache_data(ttl=300)
def load_accounts(token):
    FacebookAdsApi.init(access_token=token)
    me = User(fbid="me")
    accounts = list(me.get_ad_accounts(fields=["id","name","account_status","currency","timezone_name"]))
    return accounts

@st.cache_data(ttl=300)
def load_campaign_insights(account_id, token, date_preset):
    FacebookAdsApi.init(access_token=token)
    acc = AdAccount(account_id)
    insights = list(acc.get_insights(
        fields=["campaign_id","campaign_name","impressions","clicks","spend",
                "reach","ctr","cpc","cpm","frequency","actions","cost_per_action_type"],
        params={"date_preset": date_preset, "level": "campaign"},
    ))
    campaigns = list(acc.get_campaigns(fields=["id","name","daily_budget","lifetime_budget","status"]))
    return insights, campaigns

@st.cache_data(ttl=300)
def load_adset_insights(account_id, token, date_preset):
    FacebookAdsApi.init(access_token=token)
    acc = AdAccount(account_id)
    return list(acc.get_insights(
        fields=["campaign_name","adset_name","impressions","clicks","spend","reach","ctr","cpc","actions"],
        params={"date_preset": date_preset, "level": "adset"},
    ))

@st.cache_data(ttl=300)
def load_ad_insights(account_id, token, date_preset):
    FacebookAdsApi.init(access_token=token)
    acc = AdAccount(account_id)
    return list(acc.get_insights(
        fields=["campaign_name","adset_name","ad_name","impressions","clicks","spend",
                "reach","ctr","cpc","cpm","frequency","actions"],
        params={"date_preset": date_preset, "level": "ad"},
    ))

# --- UI ---
st.title("📊 FastLine Ads Dashboard")

if not ACCESS_TOKEN:
    st.error("Токен не знайдено. Додай META_ACCESS_TOKEN у Streamlit Secrets.")
    st.stop()

try:
    accounts = load_accounts(ACCESS_TOKEN)
except Exception as e:
    st.error(f"Помилка підключення: {e}")
    st.stop()

# Sidebar
with st.sidebar:
    st.header("Налаштування")
    account_options = {f"{a.get('name')} ({a.get('currency')})": a.get("id") for a in accounts}
    selected_name = st.selectbox("Акаунт", list(account_options.keys()))
    account_id = account_options[selected_name]

    date_options = {
        "Сьогодні": "today",
        "Вчора": "yesterday",
        "Останні 3 дні": "last_3d",
        "Останні 7 днів": "last_7d",
        "Останні 14 днів": "last_14d",
        "Останні 30 днів": "last_30d",
        "Цей місяць": "this_month",
        "Минулий місяць": "last_month",
    }
    selected_period = st.selectbox("Період", list(date_options.keys()), index=2)
    date_preset = date_options[selected_period]

    if st.button("🔄 Оновити дані", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption("Дані оновлюються автоматично кожні 5 хвилин")

# Tabs
tab1, tab2, tab3 = st.tabs(["📁 Кампанії", "🗂 Групи оголошень", "🎯 Оголошення"])

# --- TAB 1: CAMPAIGNS ---
with tab1:
    with st.spinner("Завантаження..."):
        try:
            insights, campaigns = load_campaign_insights(account_id, ACCESS_TOKEN, date_preset)
        except Exception as e:
            st.error(f"Помилка: {e}")
            st.stop()

    insights_map = {i["campaign_id"]: i for i in insights}

    # Metrics
    total_spend = sum(float(i.get("spend", 0)) for i in insights)
    total_clicks = sum(int(float(i.get("clicks", 0))) for i in insights)
    total_impr = sum(int(float(i.get("impressions", 0))) for i in insights)
    total_leads = sum(get_leads(i.get("actions", [])) for i in insights)
    avg_ctr = total_clicks / total_impr * 100 if total_impr else 0
    avg_cpc = total_spend / total_clicks if total_clicks else 0
    avg_cpl = total_spend / total_leads if total_leads else 0

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Витрати", f"zł{total_spend:,.2f}")
    col2.metric("Покази", f"{total_impr:,}")
    col3.metric("Кліки", f"{total_clicks:,}")
    col4.metric("Ліди", str(total_leads))
    col5.metric("Avg CTR", f"{avg_ctr:.2f}%")
    col6.metric("Avg CPC", f"zł{avg_cpc:.2f}")

    st.divider()

    # Campaign table
    rows = []
    for c in campaigns:
        cid = c["id"]
        ins = insights_map.get(cid)
        if ins:
            actions = ins.get("actions", [])
            leads = get_leads(actions)
            spend = float(ins.get("spend", 0))
            clicks = int(float(ins.get("clicks", 0)))
            impr = int(float(ins.get("impressions", 0)))
            ctr = float(ins.get("ctr", 0))
            cpc = float(ins.get("cpc", 0)) if ins.get("cpc") else 0
            cpl = spend / leads if leads > 0 else None
        else:
            leads = spend = clicks = impr = ctr = cpc = 0
            cpl = None

        rows.append({
            "Кампанія": c.get("name", ""),
            "Статус": c.get("status", ""),
            "Покази": impr,
            "Кліки": clicks,
            "Витрати (zł)": round(spend, 2),
            "CTR (%)": round(ctr, 2),
            "CPC (zł)": round(cpc, 2),
            "Ліди": leads,
            "CPL (zł)": round(cpl, 2) if cpl else None,
            "Бюджет": fmt_budget(c),
        })

    rows.sort(key=lambda x: x["Витрати (zł)"], reverse=True)
    df = pd.DataFrame(rows)

    active_only = st.checkbox("Тільки активні кампанії", value=True)
    if active_only:
        df = df[df["Статус"] == "ACTIVE"]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPL (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
        }
    )

    if not df.empty:
        st.bar_chart(df.set_index("Кампанія")["Витрати (zł)"])

# --- TAB 2: AD SETS ---
with tab2:
    with st.spinner("Завантаження..."):
        try:
            adset_insights = load_adset_insights(account_id, ACCESS_TOKEN, date_preset)
        except Exception as e:
            st.error(f"Помилка: {e}")
            st.stop()

    rows = []
    for i in adset_insights:
        leads = get_leads(i.get("actions", []))
        spend = float(i.get("spend", 0))
        rows.append({
            "Кампанія": i.get("campaign_name", ""),
            "Група оголошень": i.get("adset_name", ""),
            "Покази": int(float(i.get("impressions", 0))),
            "Кліки": int(float(i.get("clicks", 0))),
            "Витрати (zł)": round(spend, 2),
            "CTR (%)": round(float(i.get("ctr", 0)), 2),
            "CPC (zł)": round(float(i.get("cpc", 0)), 2) if i.get("cpc") else 0,
            "Ліди": leads,
            "CPL (zł)": round(spend / leads, 2) if leads > 0 else None,
        })

    rows.sort(key=lambda x: x["Витрати (zł)"], reverse=True)
    df2 = pd.DataFrame(rows)

    if not df2.empty:
        campaign_filter = st.multiselect("Фільтр по кампанії", df2["Кампанія"].unique())
        if campaign_filter:
            df2 = df2[df2["Кампанія"].isin(campaign_filter)]

    st.dataframe(
        df2,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPL (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
        }
    )

# --- TAB 3: ADS ---
with tab3:
    with st.spinner("Завантаження..."):
        try:
            ad_insights = load_ad_insights(account_id, ACCESS_TOKEN, date_preset)
        except Exception as e:
            st.error(f"Помилка: {e}")
            st.stop()

    rows = []
    for i in ad_insights:
        leads = get_leads(i.get("actions", []))
        spend = float(i.get("spend", 0))
        rows.append({
            "Оголошення": i.get("ad_name", ""),
            "Кампанія": i.get("campaign_name", ""),
            "Покази": int(float(i.get("impressions", 0))),
            "Кліки": int(float(i.get("clicks", 0))),
            "Витрати (zł)": round(spend, 2),
            "Охоплення": int(float(i.get("reach", 0))),
            "CTR (%)": round(float(i.get("ctr", 0)), 2),
            "CPC (zł)": round(float(i.get("cpc", 0)), 2) if i.get("cpc") else 0,
            "CPM (zł)": round(float(i.get("cpm", 0)), 2) if i.get("cpm") else 0,
            "Частота": round(float(i.get("frequency", 0)), 2) if i.get("frequency") else 0,
            "Ліди": leads,
            "CPL (zł)": round(spend / leads, 2) if leads > 0 else None,
        })

    rows.sort(key=lambda x: x["Витрати (zł)"], reverse=True)
    df3 = pd.DataFrame(rows)

    if not df3.empty:
        camp_filter = st.multiselect("Фільтр по кампанії", df3["Кампанія"].unique(), key="ad_camp_filter")
        if camp_filter:
            df3 = df3[df3["Кампанія"].isin(camp_filter)]

    st.dataframe(
        df3,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPM (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CPL (zł)": st.column_config.NumberColumn(format="zł%.2f"),
            "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
        }
    )
