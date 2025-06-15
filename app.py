import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from streamlit.runtime.scriptrunner import RerunException, RerunData
import folium
from streamlit_folium import st_folium

# Streamlit 설정
st.set_page_config(layout="centered", page_title="버스 혼잡도 대시보드")

# Firebase 초기화
firebase_info = dict(st.secrets["firebase"])
firebase_info["private_key"] = firebase_info["private_key"].replace("\\n", "\n")
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_info)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# 상수
USER_ID = "anonymous_user"
DEFAULT_LOCATION = (36.3504, 127.3845)  # 대전 중심 좌표

# Firestore 함수 캐시 적용

def add_favorite_bus(bus_no):
    ref = db.collection("favorites").document(USER_ID)
    doc = ref.get()
    favorites = doc.to_dict().get("favorite_buses", []) if doc.exists else []
    if bus_no not in favorites:
        favorites.append(bus_no)
        ref.set({"favorite_buses": favorites})
    # 캐시 초기화 필요 (아래 참고)

def remove_favorite_bus(bus_no):
    ref = db.collection("favorites").document(USER_ID)
    doc = ref.get()
    if doc.exists:
        favorites = doc.to_dict().get("favorite_buses", [])
        if bus_no in favorites:
            favorites.remove(bus_no)
            ref.set({"favorite_buses": favorites})
    # 캐시 초기화 필요 (아래 참고)

@st.cache_data(ttl=300)  # 5분 캐시 유지
def get_favorite_buses():
    doc = db.collection("favorites").document(USER_ID).get()
    return doc.to_dict().get("favorite_buses", []) if doc.exists else []

@st.cache_data(ttl=300)
def get_congestion_by_bus_number(bus_no):
    try:
        docs = db.collection("bus_congestion")\
            .where("bus_number", "==", bus_no)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(1).stream()
        doc = next(docs, None)
        return doc.to_dict() if doc else None
    except Exception as e:
        st.error(f"Firestore 쿼리 에러: {e}")
        return None

@st.cache_data(ttl=300)
def get_congestion_history(bus_no, hours=24):
    try:
        threshold = datetime.utcnow() - timedelta(hours=hours)
        docs = db.collection("bus_congestion")\
            .where("bus_number", "==", bus_no)\
            .where("timestamp", ">=", threshold)\
            .order_by("timestamp")\
            .stream()
        return [{"timestamp": d.to_dict().get("timestamp").to_datetime(), 
                 "total_congestion": d.to_dict().get("total_congestion", 0)} for d in docs]
    except Exception as e:
        st.error(f"기록 조회 실패: {e}")
        return []

@st.cache_data(ttl=3600)
def get_all_stations():
    try:
        return [{"name": d.to_dict().get("정류장명"),
                 "lat": float(d.to_dict().get("위도", 0)),
                 "lon": float(d.to_dict().get("경도", 0))} for d in db.collection("bus_stations").stream()]
    except Exception as e:
        st.error(f"정류소 로드 실패: {e}")
        return []

def search_stations_local(stations, query):
    return [s for s in stations if query.lower() in s["name"].lower()]

def rerun():
    raise RerunException(RerunData())

def congestion_status_style(congestion):
    if congestion >= 80:
        return "#ff4b4b", "혼잡"
    elif congestion >= 50:
        return "#ffdd57", "보통"
    else:
        return "#4caf50", "여유"

# 캐시 무효화용 함수 (즐겨찾기 추가/삭제 후 호출 필요)
def clear_favorites_cache():
    get_favorite_buses.clear()
    # 해당 버스들의 혼잡도도 새로고침 필요할 수 있음
    # 캐시는 자동 만료되지만 즉시 반영 원하면 직접 clear 호출 가능

# URL 파라미터 처리
query_params = st.query_params
if "remove" in query_params:
    remove_favorite_bus(query_params["remove"][0])
    clear_favorites_cache()
    st.experimental_set_query_params()
    rerun()

# 사이드바
with st.sidebar:
    st.title("메뉴")
    selected_page = st.radio("Navigate", ["Home", "Search Bus", "Search Station"], index=0)

# 페이지별 내용
if selected_page == "Home":
    st.title("🚌 대전 시내버스 혼잡도")
    favorites = get_favorite_buses()
    st.session_state.setdefault("selected_bus", None)

    if favorites:
        st.subheader("⭐ 즐겨찾기한 버스")
        cols = st.columns(len(favorites))
        for i, bus in enumerate(favorites):
            data = get_congestion_by_bus_number(bus)
            if data:
                cong = data.get("total_congestion", 0)
                time = data.get("timestamp")
                dt = time.to_datetime() if time else None
                color, status = congestion_status_style(cong)
                with cols[i]:
                    if st.button(bus, key=f"btn_{bus}"):
                        st.session_state.selected_bus = bus
                    st.markdown(f"""
                        <div style='background:{color}; padding:10px; border-radius:6px;'>
                            <b>{cong:.1f}%</b> ({status})<br/>
                            <small>{dt.strftime('%m-%d %H:%M:%S') if dt else '정보 없음'}</small><br/>
                            <a href='?remove={bus}'>삭제 ✖</a>
                        </div>
                    """, unsafe_allow_html=True)
            else:
                with cols[i]:
                    st.button(bus, key=f"btn_{bus}")
                    st.markdown("혼잡도 정보 없음")
    else:
        st.info("즐겨찾기한 버스가 없습니다.")

    if st.session_state.selected_bus:
        st.markdown("---")
        st.subheader(f"🕒 {st.session_state.selected_bus} 버스 혼잡도 추이")
        history = get_congestion_history(st.session_state.selected_bus)
        times = [h["timestamp"] for h in history if h["timestamp"]]
        values = [h["total_congestion"] for h in history if h["timestamp"]]

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

        stations = get_all_stations()
        m = folium.Map(location=DEFAULT_LOCATION, zoom_start=13)
        for s in stations:
            folium.Marker([s["lat"], s["lon"]], popup=s["name"], icon=folium.Icon(color="blue", icon="bus", prefix="fa")).add_to(m)
        st_folium(m, width=700, height=500)

    if st.button("새로고침"):
        clear_favorites_cache()
        rerun()

elif selected_page == "Search Bus":
    st.title("🔍 버스 번호 검색")
    bus_no = st.text_input("버스 번호 입력", placeholder="예: 314")
    if bus_no:
        data = get_congestion_by_bus_number(bus_no)
        if data:
            cong = data.get("total_congestion", 0)
            time = data.get("timestamp")
            dt = time.to_datetime() if time else None
            color, status = congestion_status_style(cong)
            st.markdown(f"""
                <div style='background:{color}; padding:10px; border-radius:6px;'>
                    <h3>{bus_no}번 버스 혼잡도: {cong:.1f}% ({status})</h3>
                    <p>측정시간: {dt.strftime('%Y-%m-%d %H:%M:%S') if dt else '정보 없음'}</p>
                </div>
            """, unsafe_allow_html=True)
            if st.button("즐겨찾기 추가"):
                add_favorite_bus(bus_no)
                clear_favorites_cache()
                st.success("즐겨찾기에 추가되었습니다.")
        else:
            st.warning("혼잡도 정보 없음")

elif selected_page == "Search Station":
    st.title("🔍 정류장 검색")
    stations = get_all_stations()
    query = st.text_input("정류장 이름 검색")
    if query:
        matched = search_stations_local(stations, query)
        if matched:
            st.write(f"{len(matched)}건 검색됨:")
            for s in matched:
                st.write(f"- {s['name']} (위도: {s['lat']:.5f}, 경도: {s['lon']:.5f})")
        else:
            st.info("검색 결과 없음")

    if st.button("새로고침"):
        clear_favorites_cache()
        rerun()
