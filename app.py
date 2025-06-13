import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from streamlit.runtime.scriptrunner import RerunException, RerunData
import folium
from streamlit_folium import st_folium
import requests

st.set_page_config(layout="centered", page_title="버스 혼잡도 대시보드")

# Firebase 초기화
if not firebase_admin._apps:
    cred = credentials.Certificate("account_key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

USER_ID = "anonymous_user"

def get_ip_location():
    try:
        res = requests.get("https://ipinfo.io/json")
        data = res.json()
        loc = data.get("loc", "36.3504,127.3845").split(",")
        return float(loc[0]), float(loc[1])
    except:
        return 36.3504, 127.3845  # 대전 중심 좌표 fallback

def add_favorite_bus(bus_no):
    doc_ref = db.collection("favorites").document(USER_ID)
    doc = doc_ref.get()
    if doc.exists:
        favorites = doc.to_dict().get("favorite_buses", [])
        if bus_no not in favorites:
            favorites.append(bus_no)
            doc_ref.set({"favorite_buses": favorites})
    else:
        doc_ref.set({"favorite_buses": [bus_no]})

def remove_favorite_bus(bus_no):
    doc_ref = db.collection("favorites").document(USER_ID)
    doc = doc_ref.get()
    if doc.exists:
        favorites = doc.to_dict().get("favorite_buses", [])
        if bus_no in favorites:
            favorites.remove(bus_no)
            doc_ref.set({"favorite_buses": favorites})

def get_favorite_buses():
    doc_ref = db.collection("favorites").document(USER_ID)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict().get("favorite_buses", [])
    return []

def get_congestion_by_bus_number(bus_no):
    try:
        docs = db.collection("bus_congestion")\
                 .where("bus_number", "==", bus_no)\
                 .order_by("timestamp", direction=firestore.Query.DESCENDING)\
                 .limit(1).stream()
        for doc in docs:
            return doc.to_dict()
    except Exception as e:
        st.error(f"Firestore 쿼리 에러: {e}")
    return None

def get_congestion_history(bus_no, hours=24):
    try:
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        docs = db.collection("bus_congestion")\
                 .where("bus_number", "==", bus_no)\
                 .where("timestamp", ">=", time_threshold)\
                 .order_by("timestamp")\
                 .stream()
        records = []
        for doc in docs:
            data = doc.to_dict()
            ts = data.get("timestamp")
            dt = ts.to_datetime() if hasattr(ts, "to_datetime") else None
            records.append({"timestamp": dt, "total_congestion": data.get("total_congestion", 0)})
        return records
    except Exception as e:
        st.error(f"혼잡도 기록 조회 실패: {e}")
        return []

@st.cache_data(ttl=3600)
def get_all_stations():
    stations = []
    try:
        docs = db.collection("bus_stations").stream()
        for doc in docs:
            data = doc.to_dict()
            try:
                lat = float(data.get("위도", "0"))
                lon = float(data.get("경도", "0"))
                name = data.get("정류장명", "")
                stations.append({"name": name, "lat": lat, "lon": lon})
            except:
                continue
        return stations
    except Exception as e:
        st.error(f"정류소 전체 불러오기 오류: {e}")
        return []

def search_stations_local(stations, query):
    return [s for s in stations if query.lower() in s["name"].lower()]

def rerun():
    raise RerunException(RerunData())

# 쿼리 파라미터에서 삭제 요청 처리
query_params = st.query_params
if "remove" in query_params:
    bus_to_remove = query_params["remove"][0]
    remove_favorite_bus(bus_to_remove)
    st.experimental_set_query_params()
    rerun()

with st.sidebar:
    st.title("메뉴")
    selected_page = st.radio("Navigate", ["Home", "Search Bus", "Search Station"], index=0)

def congestion_status_style(congestion):
    if congestion >= 80:
        return "#ff4b4b", "혼잡"
    elif congestion >= 50:
        return "#ffdd57", "보통"
    else:
        return "#4caf50", "여유"

if selected_page == "Home":
    st.title("🚌 대전광역시 시내버스 혼잡도 대시보드")
    favorites = get_favorite_buses()

    if "selected_bus" not in st.session_state:
        st.session_state.selected_bus = None

    if favorites:
        st.subheader("⭐ 즐겨찾기한 버스 목록")
        cols = st.columns(len(favorites))
        for idx, bus_no in enumerate(favorites):
            congestion_data = get_congestion_by_bus_number(bus_no)
            if congestion_data:
                congestion = congestion_data.get('total_congestion', 0)
                timestamp = congestion_data.get('timestamp')
                timestamp = timestamp.to_datetime() if hasattr(timestamp, 'to_datetime') else None
                bg_color, status_text = congestion_status_style(congestion)
                with cols[idx]:
                    if st.button(bus_no, key=f"fav_bus_{bus_no}"):
                        st.session_state.selected_bus = bus_no
                    st.markdown(f"""
                        <div style="background-color: {bg_color}; padding: 10px; border-radius: 6px;">
                        <p style="margin:0;"><b>{congestion:.1f}%</b> ({status_text})</p>
                        <p style="font-size: 10px;">{timestamp.strftime('%m-%d %H:%M:%S') if timestamp else '정보 없음'}</p>
                        <a href="?remove={bus_no}">삭제 ✖</a>
                        </div>
                    """, unsafe_allow_html=True)
            else:
                with cols[idx]:
                    if st.button(bus_no, key=f"fav_bus_{bus_no}"):
                        st.session_state.selected_bus = bus_no
                    st.markdown("혼잡도 정보 없음")
    else:
        st.write("즐겨찾기한 버스가 없습니다.")

    if st.session_state.selected_bus:
        st.markdown("---")
        st.subheader(f"🕒 '{st.session_state.selected_bus}' 버스 시간대별 혼잡도 그래프")
        history = get_congestion_history(st.session_state.selected_bus)

        times = [rec["timestamp"] for rec in history if rec["timestamp"]]
        values = [rec["total_congestion"] for rec in history if rec["timestamp"]]

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

        # 현재 위치 위도/경도 텍스트만 표시 (지도 마커 없음)
        lat, lon = get_ip_location()
        st.info(f"현재 위치 (위도, 경도): ({lat:.5f}, {lon:.5f})")

        # 정류장 위치만 지도에 마커로 표시
        stations = get_all_stations()
        m = folium.Map(location=[lat, lon], zoom_start=13)
        for s in stations:
            folium.Marker([s["lat"], s["lon"]], popup=s["name"], icon=folium.Icon(color="blue", icon="bus", prefix="fa")).add_to(m)
        st_folium(m, width=700, height=500)

    if st.button("새로고침"):
        rerun()

elif selected_page == "Search Bus":
    st.title("🔍 버스 번호 검색")
    bus_number = st.text_input("버스 번호 입력", placeholder="예: 314")

    if bus_number:
        st.success(f"{bus_number}번 버스를 검색했습니다.")

        if st.button("⭐ 즐겨찾기에 추가"):
            add_favorite_bus(bus_number)
            st.success("추가 완료!")
            rerun()

        congestion_data = get_congestion_by_bus_number(bus_number)
        if congestion_data:
            congestion = congestion_data.get('total_congestion', 0)
            timestamp = congestion_data.get('timestamp')
            timestamp = timestamp.to_datetime() if hasattr(timestamp, 'to_datetime') else None
            bg_color, status_text = congestion_status_style(congestion)
            st.markdown(f"""
            <div style="background-color: {bg_color}; padding: 15px; border-radius: 8px;">
            혼잡도: <b>{congestion:.1f}%</b> ({status_text})<br>
            최근 시간: {timestamp.strftime('%Y-%m-%d %H:%M:%S') if timestamp else '정보 없음'}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("해당 버스 데이터 없음")

elif selected_page == "Search Station":
    st.title("🗺️ 정류장 이름으로 검색")

    lat, lon = get_ip_location()

    query = st.text_input("정류장명을 입력하세요")

    all_stations = get_all_stations()

    if query:
        results = search_stations_local(all_stations, query)
        st.write(f"검색 결과: {len(results)}개")
        if results:
            # 정류장명 텍스트 목록 먼저 출력
            st.subheader("검색된 정류장 목록")
            for s in results:
                st.write(f"- {s['name']}")

            # 그 아래에 지도 출력 (마커만)
            m = folium.Map(location=[lat, lon], zoom_start=13)
            for s in results:
                folium.Marker([s["lat"], s["lon"]], popup=s["name"], icon=folium.Icon(color="green", icon="info-sign")).add_to(m)
            st_folium(m, width=700, height=500)
        else:
            st.write("검색 결과가 없습니다.")


st.markdown("---")
st.markdown("Developed for Capstone Project | © Your University")
