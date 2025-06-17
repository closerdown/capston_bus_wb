from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import os
import json

app = Flask(__name__)
CORS(app)

# 환경변수에서 Firebase 서비스 계정 키 불러오기
account_key_str = os.getenv("account_key")

if not account_key_str:
    raise RuntimeError("환경변수 'account_key'가 설정되지 않았습니다.")

firebase_info = json.loads(account_key_str)

# private_key 안의 '\\n'을 실제 개행문자 '\n'으로 변환
if 'private_key' in firebase_info:
    firebase_info['private_key'] = firebase_info['private_key'].replace('\\n', '\n')

# Firebase 초기화
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_info)
    firebase_admin.initialize_app(cred)

db = firestore.client()

USER_ID = "anonymous_user"

@app.route("/favorites", methods=["GET"])
def get_favorites():
    doc = db.collection("favorites").document(USER_ID).get()
    favorites = doc.to_dict().get("favorite_buses", []) if doc.exists else []
    return jsonify({"favorites": favorites})

@app.route("/favorites", methods=["POST"])
def add_favorite():
    bus_no = request.json.get("bus_no")
    if not bus_no:
        return jsonify({"error": "bus_no is required"}), 400

    ref = db.collection("favorites").document(USER_ID)
    doc = ref.get()
    favorites = doc.to_dict().get("favorite_buses", []) if doc.exists else []

    if bus_no not in favorites:
        favorites.append(bus_no)
        ref.set({"favorite_buses": favorites})

    return jsonify({"favorites": favorites})

@app.route("/favorites/<bus_no>", methods=["DELETE"])
def remove_favorite(bus_no):
    ref = db.collection("favorites").document(USER_ID)
    doc = ref.get()
    if doc.exists:
        favorites = doc.to_dict().get("favorite_buses", [])
        if bus_no in favorites:
            favorites.remove(bus_no)
            ref.set({"favorite_buses": favorites})
    return jsonify({"favorites": favorites})

@app.route("/congestion/<bus_no>", methods=["GET"])
def get_congestion(bus_no):
    try:
        docs = db.collection("bus_congestion")\
            .where("bus_number", "==", bus_no)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(1).stream()
        doc = next(docs, None)
        if doc:
            data = doc.to_dict()
            data["timestamp"] = data["timestamp"].isoformat()  # 수정된 부분
            return jsonify(data)
        else:
            return jsonify({"error": "No data found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/congestion_history/<bus_no>", methods=["GET"])
def get_congestion_history(bus_no):
    hours = int(request.args.get("hours", 24))
    try:
        threshold = datetime.utcnow() - timedelta(hours=hours)
        docs = db.collection("bus_congestion")\
            .where("bus_number", "==", bus_no)\
            .where("timestamp", ">=", threshold)\
            .order_by("timestamp")\
            .stream()
        history = []
        for d in docs:
            d_dict = d.to_dict()
            history.append({
                "timestamp": d_dict["timestamp"].isoformat(),  # 수정된 부분
                "total_congestion": d_dict.get("total_congestion", 0)
            })
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stations", methods=["GET"])
def get_stations():
    try:
        stations = []
        docs = db.collection("bus_stations").stream()
        for d in docs:
            d_dict = d.to_dict()
            stations.append({
                "name": d_dict.get("정류장명"),
                "lat": float(d_dict.get("위도", 0)),
                "lon": float(d_dict.get("경도", 0))
            })
        return jsonify(stations)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
