import streamlit as st


def apply_styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

    /* the main page */
    .stApp { background: #FFF8F1; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stDecoration"] { display: none; }
    .block-container { max-width: 1600px; padding: 4.2rem 1.3rem 2rem 1.3rem; }
    h1, h2, h3 { color: #20283D !important; }
    p, label, .stCaption { color: #657187; }

    /* the sidebar */
    [data-testid="stSidebar"] { background: #20283D; border-right: 3px solid #FC8019; }
    [data-testid="stSidebar"] * { color: #F8FAFC; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #F8FAFC !important; }
    [data-testid="stSidebar"] [data-baseweb="select"] > div { background: #0F1626 !important; }
    [data-testid="stSidebar"] [data-baseweb="input"] { background: #0F1626 !important; }

    /* the white cards */
    [data-testid="stMetric"] { background: white; border: 1px solid #F0E3D7; border-radius: 12px; padding: 14px; }
    [data-testid="stMetricLabel"] { color: #657187 !important; }
    [data-testid="stMetricValue"] { color: #20283D !important; font-weight: 800; font-size: 1.5rem; }
    [data-testid="stVerticalBlockBorderWrapper"] { background: white; border: 1px solid #F0E3D7; border-radius: 14px; padding: 12px; }
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] { background: transparent; border: 0; padding: 0; }

    /* the orange top banner */
    .topbar { display: flex; justify-content: space-between; align-items: center; padding: 18px 22px; margin-bottom: 12px; background: #FFF0DF; border: 1px solid #F0E3D7; border-left: 5px solid #FC8019; border-radius: 14px; }
    .topbar h1 { margin: 4px 0; }
    .eyebrow { color: #FC8019; font-size: 12px; font-weight: 800; letter-spacing: 1px; }
    .subhead { color: #657187; font-size: 14px; }
    .live-pill { background: white; border: 1px solid #F0E3D7; border-radius: 12px; padding: 10px 14px; color: #20283D; font-size: 13px; font-weight: 700; }
    .live-pill small { color: #657187; font-weight: 400; }
    .live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #35A36A; margin-right: 6px; }
    .panel-title { color: #20283D; font-size: 16px; font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)