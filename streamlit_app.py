import streamlit as st
import requests
import matplotlib.pyplot as plt
from datetime import datetime
import folium
from streamlit_folium import st_folium

st.set_page_config(layout="centered", page_title="버스 혼잡도 대시보드")

API_URL = st.secrets["api"]["base_url"]
DEFAULT_LOCATION = (36.3504, 127.3845)  # 대전 중심 좌표

# --------------------- API 함수 ---------------------
def get_favorite_buses():
    try:
        res = requests.get(f"{API_URL}/favorites")
        if res.status_code == 200:
            return res.json().get("favorites", [])
    except:
        pass
    return []

def add_favorite_bus(bus_no):
    res = requests.post(f"{API_URL}/favorites", json={"bus_no": bus_no})
    return res.status_code == 200

def remove_favorite_bus(bus_no):
    res = requests.delete(f"{API_URL}/favorites/{bus_no}")
    return res.status_code == 200

def get_congestion_by_bus_number(bus_no):
    res = requests.get(f"{API_URL}/congestion/{bus_no}")
    return res.json() if res.status_code == 200 else None

def get_congestion_history(bus_no, hours=24):
    res = requests.get(f"{API_URL}/congestion_history/{bus_no}?hours={hours}")
    return res.json() if res.status_code == 200 else []

def get_all_stations():
    res = requests.get(f"{API_URL}/stations")
    return res.json() if res.status_code == 200 else []

# ------------------- 유틸 함수 ---------------------
def congestion_status_style(congestion):
    if congestion >= 80:
        return "#ff4b4b", "혼잡"
    elif congestion >= 50:
        return "#ffdd57", "보통"
    else:
        return "#4caf50", "여유"

# ----------------- 쿼리 파라미터 처리 -----------------
query_params = st.query_params
bus_to_remove = query_params.get("remove", [None])[0]
if bus_to_remove:
    if remove_favorite_bus(bus_to_remove):
        st.success(f"{bus_to_remove} 삭제됨")
    else:
        st.error("삭제 실패")
    st.experimental_set_query_params()
    st.stop()  # rerun 대신 stop으로 안전하게 종료 후 재실행 유도

# ------------------- UI 레이아웃 ----------------------
with st.sidebar:
    st.title("메뉴")
    selected_page = st.radio("Navigate", ["Home", "Search Bus", "Search Station"], index=0)

# ---------------------- Home ----------------------
if selected_page == "Home":
    st.title("🚌 대전 시내버스 혼잡도")

    # 🔄 새로고침 버튼
    if st.button("🔄 새로고침"):
        st.experimental_rerun()

    favorites = get_favorite_buses()
    st.session_state.setdefault("selected_bus", None)

    if favorites:
        st.subheader("⭐ 즐겨찾기한 버스")
        cols = st.columns(len(favorites))
        for i, bus in enumerate(favorites):
            data = get_congestion_by_bus_number(bus)
            with cols[i]:
                if st.button(bus, key=f"btn_{bus}"):
                    st.session_state.selected_bus = bus
                if data:
                    cong = data.get("total_congestion", 0)
                    time = data.get("timestamp")
                    dt = datetime.fromisoformat(time) if time else None
                    color, status = congestion_status_style(cong)
                    st.markdown(f"""
                        <div style='background:{color}; padding:10px; border-radius:6px;'>
                            <b>{cong:.1f}%</b> ({status})<br/>
                            <small>{dt.strftime('%m-%d %H:%M:%S') if dt else '정보 없음'}</small><br/>
                            <a href='?remove={bus}'>삭제 ✖</a>
                        </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown("혼잡도 정보 없음")
    else:
        st.info("즐겨찾기한 버스가 없습니다.")

    # 선택된 버스 그래프
    if st.session_state.selected_bus:
        st.markdown("---")
        st.subheader(f"🕒 {st.session_state.selected_bus} 버스 혼잡도 추이")
        history = get_congestion_history(st.session_state.selected_bus)
        times = [datetime.fromisoformat(h["timestamp"]) for h in history if h["timestamp"]]
        values = [h["total_congestion"] for h in history]

        if times and values:
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(times, values, marker='o', color='dodgerblue')
            ax.set_title("혼잡도 추이")
            ax.set_xlabel("시간")
            ax.set_ylabel("혼잡도 (%)")
            plt.xticks(rotation=45)
            st.pyplot(fig)
        else:
            st.info("표시할 데이터가 없습니다.")

# ------------------- Search Bus -------------------
elif selected_page == "Search Bus":
    st.title("버스 번호로 검색")
    bus_no = st.text_input("버스 번호 입력")
    if st.button("검색") and bus_no:
        congestion = get_congestion_by_bus_number(bus_no)
        if congestion:
            cong = congestion.get("total_congestion", 0)
            color, status = congestion_status_style(cong)
            st.markdown(f"<h2 style='color:{color}'>혼잡도: {cong:.1f}% ({status})</h2>", unsafe_allow_html=True)
            if st.button("즐겨찾기에 추가"):
                if add_favorite_bus(bus_no):
                    st.success(f"{bus_no} 즐겨찾기 추가됨")
                    st.experimental_rerun()
                else:
                    st.error("추가 실패")
        else:
            st.warning("해당 버스에 대한 정보가 없습니다.")

# ------------------ Search Station -----------------
elif selected_page == "Search Station":
    st.title("정류장 검색")
    stations = get_all_stations()
    search_name = st.text_input("정류장명 입력")
    filtered = [s for s in stations if search_name in s["name"]] if search_name else []

    for s in filtered:
        st.write(s['name'])

    if filtered:
        center_lat = filtered[0]['lat']
        center_lon = filtered[0]['lon']
        m = folium.Map(location=(center_lat, center_lon), zoom_start=14)
        for s in filtered:
            folium.Marker([s["lat"], s["lon"]], popup=s["name"],
                          icon=folium.Icon(color="blue", icon="bus", prefix="fa")).add_to(m)
        st_folium(m, width=700)
    else:
        st.info("검색 결과가 없습니다.")
