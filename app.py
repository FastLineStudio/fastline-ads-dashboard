import streamlit as st
import os
import pandas as pd
import requests
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.user import User

st.set_page_config(page_title="FastLine Ads Dashboard", page_icon="📊", layout="wide")

def fmt(val, sym="zł"):
    try:
        return f"{sym}{float(val):,.2f}"
    except:
        return "-"

def get_leads(actions):
    if not actions:
        return 0
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

def load_accounts(token):
    FacebookAdsApi.init(access_token=token)
    me = User(fbid="me")
    accounts = me.get_ad_accounts(fields=["id","name","account_status","currency","timezone_name"])
    return [{"id": a["id"], "name": a["name"], "account_status": a.get("account_status"),
             "currency": a.get("currency"), "timezone_name": a.get("timezone_name")} for a in accounts]

def load_campaign_insights(account_id, token, date_preset):
    FacebookAdsApi.init(access_token=token)
    acc = AdAccount(account_id)
    insights_raw = acc.get_insights(
        fields=["campaign_id","campaign_name","impressions","clicks","spend",
                "reach","ctr","cpc","cpm","frequency","actions","cost_per_action_type"],
        params={"date_preset": date_preset, "level": "campaign"},
    )
    insights = [dict(i) for i in insights_raw]
    campaigns_raw = acc.get_campaigns(fields=["id","name","daily_budget","lifetime_budget","status"])
    campaigns = [dict(c) for c in campaigns_raw]
    return insights, campaigns

def load_adset_insights(account_id, token, date_preset):
    FacebookAdsApi.init(access_token=token)
    acc = AdAccount(account_id)
    raw = acc.get_insights(
        fields=["campaign_name","adset_name","impressions","clicks","spend","reach","ctr","cpc","actions"],
        params={"date_preset": date_preset, "level": "adset"},
    )
    return [dict(i) for i in raw]

def load_ad_insights(account_id, token, date_preset):
    FacebookAdsApi.init(access_token=token)
    acc = AdAccount(account_id)
    raw = acc.get_insights(
        fields=["campaign_name","adset_name","ad_name","impressions","clicks","spend",
                "reach","ctr","cpc","cpm","frequency","actions"],
        params={"date_preset": date_preset, "level": "ad"},
    )
    return [dict(i) for i in raw]

GOOGLE_ACCOUNTS = {
    "FLS Poland (429-789-1329)": "4297891329",
    "Fastline (842-419-8513)": "8424198513",
}

def google_get_access_token():
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": st.secrets.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": st.secrets.get("GOOGLE_CLIENT_SECRET", ""),
            "refresh_token": st.secrets.get("GOOGLE_REFRESH_TOKEN", ""),
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def google_query(customer_id, query, access_token):
    dev_token = st.secrets.get("GOOGLE_DEVELOPER_TOKEN", "")
    mcc_id = st.secrets.get("GOOGLE_MCC_ID", "7329460296")
    url = f"https://googleads.googleapis.com/v17/customers/{customer_id}/googleAds:search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": dev_token,
        "login-customer-id": str(mcc_id),
        "Content-Type": "application/json",
    }
    results = []
    payload = {"query": query}
    while True:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        next_page = data.get("nextPageToken")
        if not next_page:
            break
        payload["pageToken"] = next_page
    return results

def load_google_campaigns(customer_id, access_token, date_range):
    query = f"""
        SELECT campaign.id, campaign.name, campaign.status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.ctr, metrics.average_cpc, metrics.conversions
        FROM campaign
        WHERE segments.date DURING {date_range}
        ORDER BY metrics.cost_micros DESC
    """
    return google_query(customer_id, query, access_token)

def load_google_ad_groups(customer_id, access_token, date_range):
    query = f"""
        SELECT campaign.name, ad_group.name, ad_group.status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.ctr, metrics.average_cpc, metrics.conversions
        FROM ad_group
        WHERE segments.date DURING {date_range}
        ORDER BY metrics.cost_micros DESC
    """
    return google_query(customer_id, query, access_token)

def parse_google_campaigns(results):
    rows = []
    for r in results:
        m = r.get("metrics", {})
        cost = int(m.get("costMicros", 0)) / 1_000_000
        cpc = int(m.get("averageCpc", 0)) / 1_000_000
        clicks = int(m.get("clicks", 0))
        impr = int(m.get("impressions", 0))
        ctr = float(m.get("ctr", 0)) * 100
        rows.append({
            "Кампанія": r.get("campaign", {}).get("name", ""),
            "Статус": r.get("campaign", {}).get("status", ""),
            "Покази": impr, "Кліки": clicks,
            "Витрати (zł)": round(cost, 2),
            "CTR (%)": round(ctr, 2),
            "CPC (zł)": round(cpc, 2),
            "Конверсії": round(float(m.get("conversions", 0)), 2),
        })
    return rows

def parse_google_ad_groups(results):
    rows = []
    for r in results:
        m = r.get("metrics", {})
        cost = int(m.get("costMicros", 0)) / 1_000_000
        cpc = int(m.get("averageCpc", 0)) / 1_000_000
        rows.append({
            "Кампанія": r.get("campaign", {}).get("name", ""),
            "Група оголошень": r.get("adGroup", {}).get("name", ""),
            "Статус": r.get("adGroup", {}).get("status", ""),
            "Покази": int(m.get("impressions", 0)),
            "Кліки": int(m.get("clicks", 0)),
            "Витрати (zł)": round(cost, 2),
            "CTR (%)": round(float(m.get("ctr", 0)) * 100, 2),
            "CPC (zł)": round(cpc, 2),
            "Конверсії": round(float(m.get("conversions", 0)), 2),
        })
    return rows

st.title("📊 FastLine Ads Dashboard")

ACCESS_TOKEN = st.secrets.get("META_ACCESS_TOKEN", os.getenv("META_ACCESS_TOKEN", ""))

DATE_OPTIONS = {
    "Сьогодні": ("today", "TODAY"),
    "Вчора": ("yesterday", "YESTERDAY"),
    "Останні 7 днів": ("last_7d", "LAST_7_DAYS"),
    "Останні 30 днів": ("last_30d", "LAST_30_DAYS"),
    "Цей місяць": ("this_month", "THIS_MONTH"),
    "Минулий місяць": ("last_month", "LAST_MONTH"),
}

with st.sidebar:
    st.header("Налаштування")
    selected_period = st.selectbox("Період", list(DATE_OPTIONS.keys()), index=2)
    meta_date_preset, google_date_range = DATE_OPTIONS[selected_period]

    st.divider()
    st.subheader("Meta Ads")
    meta_account_id = None
    if ACCESS_TOKEN:
        try:
            meta_accounts = load_accounts(ACCESS_TOKEN)
            account_options = {f"{a.get('name')} ({a.get('currency')})": a.get("id") for a in meta_accounts}
            if account_options:
                selected_name = st.selectbox("Акаунт Meta", list(account_options.keys()))
                meta_account_id = account_options[selected_name]
        except Exception as e:
            st.warning(f"Meta: {e}")

    st.divider()
    st.subheader("Google Ads")
    google_account_label = st.selectbox("Акаунт Google", list(GOOGLE_ACCOUNTS.keys()))
    google_customer_id = GOOGLE_ACCOUNTS[google_account_label]

    if st.button("🔄 Оновити дані", use_container_width=True):
        st.rerun()

main_tab_meta, main_tab_google = st.tabs(["📘 Meta Ads", "🟢 Google Ads"])

with main_tab_meta:
    if not ACCESS_TOKEN:
        st.error("Токен не знайдено. Додай META_ACCESS_TOKEN у Streamlit Secrets.")
    elif not meta_account_id:
        st.warning("Оберіть акаунт Meta у боковій панелі.")
    else:
        tab1, tab2, tab3 = st.tabs(["📁 Кампанії", "🗂 Групи оголошень", "🎯 Оголошення"])

        with tab1:
            with st.spinner("Завантаження..."):
                try:
                    insights, campaigns = load_campaign_insights(meta_account_id, ACCESS_TOKEN, meta_date_preset)
                except Exception as e:
                    st.error(f"Помилка: {e}")
                    insights, campaigns = [], []

            insights_map = {i["campaign_id"]: i for i in insights}
            total_spend = sum(float(i.get("spend", 0)) for i in insights)
            total_clicks = sum(int(float(i.get("clicks", 0))) for i in insights)
            total_impr = sum(int(float(i.get("impressions", 0))) for i in insights)
            total_leads = sum(get_leads(i.get("actions", [])) for i in insights)
            avg_ctr = total_clicks / total_impr * 100 if total_impr else 0
            avg_cpc = total_spend / total_clicks if total_clicks else 0

            col1, col2, col3, col4, col5, col6 = st.columns(6)
            col1.metric("Витрати", f"zł{total_spend:,.2f}")
            col2.metric("Покази", f"{total_impr:,}")
            col3.metric("Кліки", f"{total_clicks:,}")
            col4.metric("Ліди", str(total_leads))
            col5.metric("Avg CTR", f"{avg_ctr:.2f}%")
            col6.metric("Avg CPC", f"zł{avg_cpc:.2f}")
            st.divider()

            rows = []
            for c in campaigns:
                cid = c["id"]
                ins = insights_map.get(cid)
                if ins:
                    leads = get_leads(ins.get("actions", []))
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
                    "Кампанія": c.get("name", ""), "Статус": c.get("status", ""),
                    "Покази": impr, "Кліки": clicks, "Витрати (zł)": round(spend, 2),
                    "CTR (%)": round(ctr, 2), "CPC (zł)": round(cpc, 2),
                    "Ліди": leads, "CPL (zł)": round(cpl, 2) if cpl else None,
                    "Бюджет": fmt_budget(c),
                })

            rows.sort(key=lambda x: x["Витрати (zł)"], reverse=True)
            df = pd.DataFrame(rows)
            active_only = st.checkbox("Тільки активні", value=True, key="m_active")
            if active_only:
                df = df[df["Статус"] == "ACTIVE"]
            st.dataframe(df, use_container_width=True, hide_index=True,
                column_config={
                    "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CPL (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
                })
            if not df.empty:
                st.bar_chart(df.set_index("Кампанія")["Витрати (zł)"])

        with tab2:
            with st.spinner("Завантаження..."):
                try:
                    adset_insights = load_adset_insights(meta_account_id, ACCESS_TOKEN, meta_date_preset)
                except Exception as e:
                    st.error(f"Помилка: {e}")
                    adset_insights = []
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
                cf = st.multiselect("Фільтр по кампанії", df2["Кампанія"].unique(), key="m_adset_filter")
                if cf:
                    df2 = df2[df2["Кампанія"].isin(cf)]
            st.dataframe(df2, use_container_width=True, hide_index=True,
                column_config={
                    "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CPL (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
                })

        with tab3:
            with st.spinner("Завантаження..."):
                try:
                    ad_insights = load_ad_insights(meta_account_id, ACCESS_TOKEN, meta_date_preset)
                except Exception as e:
                    st.error(f"Помилка: {e}")
                    ad_insights = []
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
                    "CTR (%)": round(float(i.get("ctr", 0)), 2),
                    "CPC (zł)": round(float(i.get("cpc", 0)), 2) if i.get("cpc") else 0,
                    "Ліди": leads,
                    "CPL (zł)": round(spend / leads, 2) if leads > 0 else None,
                })
            rows.sort(key=lambda x: x["Витрати (zł)"], reverse=True)
            df3 = pd.DataFrame(rows)
            if not df3.empty:
                cf3 = st.multiselect("Фільтр по кампанії", df3["Кампанія"].unique(), key="m_ad_filter")
                if cf3:
                    df3 = df3[df3["Кампанія"].isin(cf3)]
            st.dataframe(df3, use_container_width=True, hide_index=True,
                column_config={
                    "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CPL (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                    "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
                })

with main_tab_google:
    required = ["GOOGLE_DEVELOPER_TOKEN","GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","GOOGLE_REFRESH_TOKEN"]
    missing = [s for s in required if not st.secrets.get(s)]
    if missing:
        st.error(f"Відсутні секрети: {', '.join(missing)}")
    else:
        try:
            g_token = google_get_access_token()
        except Exception as e:
            st.error(f"Не вдалося отримати токен Google: {e}")
            g_token = None

        if g_token:
            gtab1, gtab2 = st.tabs(["📁 Кампанії", "🗂 Групи оголошень"])

            with gtab1:
                with st.spinner(f"Завантаження кампаній ({google_account_label})..."):
                    try:
                        gc_results = load_google_campaigns(google_customer_id, g_token, google_date_range)
                        gc_rows = parse_google_campaigns(gc_results)
                    except Exception as e:
                        st.error(f"Помилка: {e}")
                        gc_rows = []

                if gc_rows:
                    df_gc = pd.DataFrame(gc_rows)
                    total_gc_spend = df_gc["Витрати (zł)"].sum()
                    total_gc_clicks = df_gc["Кліки"].sum()
                    total_gc_impr = df_gc["Покази"].sum()
                    total_gc_conv = df_gc["Конверсії"].sum()
                    avg_gc_ctr = total_gc_clicks / total_gc_impr * 100 if total_gc_impr else 0
                    avg_gc_cpc = total_gc_spend / total_gc_clicks if total_gc_clicks else 0

                    col1, col2, col3, col4, col5, col6 = st.columns(6)
                    col1.metric("Витрати", f"zł{total_gc_spend:,.2f}")
                    col2.metric("Покази", f"{int(total_gc_impr):,}")
                    col3.metric("Кліки", f"{int(total_gc_clicks):,}")
                    col4.metric("Конверсії", f"{total_gc_conv:.1f}")
                    col5.metric("Avg CTR", f"{avg_gc_ctr:.2f}%")
                    col6.metric("Avg CPC", f"zł{avg_gc_cpc:.2f}")
                    st.divider()

                    gc_active = st.checkbox("Тільки активні", value=True, key="g_active")
                    if gc_active:
                        df_gc = df_gc[df_gc["Статус"] == "ENABLED"]
                    st.dataframe(df_gc, use_container_width=True, hide_index=True,
                        column_config={
                            "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                            "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                            "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
                        })
                    if not df_gc.empty:
                        st.bar_chart(df_gc.set_index("Кампанія")["Витрати (zł)"])
                else:
                    st.info("Немає даних для обраного періоду.")

            with gtab2:
                with st.spinner(f"Завантаження груп ({google_account_label})..."):
                    try:
                        gag_results = load_google_ad_groups(google_customer_id, g_token, google_date_range)
                        gag_rows = parse_google_ad_groups(gag_results)
                    except Exception as e:
                        st.error(f"Помилка: {e}")
                        gag_rows = []

                if gag_rows:
                    df_gag = pd.DataFrame(gag_rows)
                    cf_g = st.multiselect("Фільтр по кампанії", df_gag["Кампанія"].unique(), key="g_ag_filter")
                    if cf_g:
                        df_gag = df_gag[df_gag["Кампанія"].isin(cf_g)]
                    st.dataframe(df_gag, use_container_width=True, hide_index=True,
                        column_config={
                            "Витрати (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                            "CPC (zł)": st.column_config.NumberColumn(format="zł%.2f"),
                            "CTR (%)": st.column_config.NumberColumn(format="%.2f%%"),
                        })
                else:
                    st.info("Немає даних для обраного періоду.")
