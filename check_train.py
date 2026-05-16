import requests
import os
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from config import NOTIFY_TARGETS

load_dotenv()

TW_TZ = timezone(timedelta(hours=8))

TDX_CLIENT_ID = os.environ["TDX_CLIENT_ID"]
TDX_CLIENT_SECRET = os.environ["TDX_CLIENT_SECRET"]


def get_tdx_token():
    url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": TDX_CLIENT_ID,
        "client_secret": TDX_CLIENT_SECRET,
    }
    res = requests.post(url, data=data)
    return res.json()["access_token"]


TDX_MIN_INTERVAL = 0.5  # 每次呼叫前至少間隔的秒數，避開 rate limit
_last_tdx_call_at = 0.0


def tdx_get(url, token, max_retries=3):
    """打 TDX API；呼叫間維持最小間隔，遇 429 自動退避重試"""
    global _last_tdx_call_at
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(max_retries):
        wait = TDX_MIN_INTERVAL - (time.time() - _last_tdx_call_at)
        if wait > 0:
            time.sleep(wait)
        res = requests.get(url, headers=headers)
        _last_tdx_call_at = time.time()
        if res.status_code == 429:
            time.sleep(2**attempt)
            continue
        return res.json()
    return {}


def get_train_live_board(token, train_no):
    """取得指定車次的即時位置與誤點資料，回傳第一筆或 None"""
    url = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/TrainLiveBoard/TrainNo/{train_no}?%24format=JSON"
    boards = tdx_get(url, token).get("TrainLiveBoards", [])
    return boards[0] if boards else None


def get_train_timetable(token, train_no):
    """取得今日該車次完整停靠站時刻"""
    url = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTrainTimetable/Today/TrainNo/{train_no}?%24format=JSON"
    data = tdx_get(url, token)
    timetables = data.get("TrainTimetables", [])
    if not timetables:
        return []
    return timetables[0].get("StopTimes", [])


def get_station_stop(stop_times, station_id):
    """從 stop_times 找出指定站的停靠資訊"""
    for stop in stop_times:
        if stop.get("StationID") == station_id:
            return stop
    return None


def get_stop_time(stop):
    """取得該站的發車時間，若無則退而取到站時間"""
    return stop.get("DepartureTime") or stop.get("ArrivalTime")


def is_completed(stop_times):
    """判斷火車是否已抵達末站完成運行"""
    if not stop_times:
        return False
    now = datetime.now(TW_TZ)
    time_str = get_stop_time(stop_times[-1])
    if not time_str:
        return False
    h, m = map(int, time_str.split(":"))
    final_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return now > final_dt


def get_status(live_board, stop_times, from_stop):
    now = datetime.now(TW_TZ)
    from_station_name = from_stop.get("StationName", {}).get("Zh_tw")

    if live_board is None:
        if is_completed(stop_times):
            return "⬛ 已完駛"
        return "⏳ 尚未發車"

    time_str = get_stop_time(from_stop)
    h, m = map(int, time_str.split(":"))
    delay_minutes = live_board.get("DelayTime", 0)
    depart_dt = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(
        minutes=delay_minutes
    )

    if now >= depart_dt:
        current_station = live_board.get("StationName", {}).get("Zh_tw", "")
        station_str = f"目前在 **{current_station}**"
        if delay_minutes > 0:
            return f"🚂 已離開{from_station_name}站，{station_str}，誤點 **{delay_minutes} 分鐘**"
        return f"🚂 已離開{from_station_name}站，{station_str}，無誤點"

    if delay_minutes > 0:
        return f"⚠️ 誤點 **{delay_minutes} 分鐘**"
    return "✅ 無誤點"


def send_discord(message, webhook_url):
    requests.post(webhook_url, json={"content": message})


def build_train_message(target, token):
    from_station_id = target["from_station"]
    trains = target["trains"]

    from_station_name = None
    train_status_lines = []
    for train_no in trains:
        stop_times = get_train_timetable(token, train_no)
        from_stop = get_station_stop(stop_times, from_station_id)

        if not from_stop:
            train_status_lines.append(f"**{train_no} 次**：⚪ 查無起站資訊")
            continue

        live_board = get_train_live_board(token, train_no)

        if from_station_name is None:
            from_station_name = from_stop.get("StationName", {}).get(
                "Zh_tw", from_station_id
            )
        depart_time = get_stop_time(from_stop)
        status = get_status(live_board, stop_times, from_stop)
        train_status_lines.append(
            f"**{train_no} 次**（{depart_time} {from_station_name}發）：{status}"
        )

    station_label = from_station_name or from_station_id
    lines = [f"🚆 **今日{station_label}出發火車誤點通知**\n"] + train_status_lines
    return "\n".join(lines)


def process_target(target, token):
    webhook_url = os.environ.get(target["webhook_env"])
    if not webhook_url:
        print(f"skip {target['name']}: env {target['webhook_env']} not set")
        return

    if target["type"] != "train":
        # 非 train 類型（如 weather）目前還沒實作
        print(f"skip {target['name']}: type={target['type']} not yet supported")
        return

    try:
        message = build_train_message(target, token)
    except Exception as e:
        message = f"🚆 **{target['name']} 通知**\n\n⚪ 查無資料（API 錯誤：{e}）"

    send_discord(message, webhook_url)
    print(message)


def main():
    try:
        token = get_tdx_token()
    except Exception as e:
        for target in NOTIFY_TARGETS:
            if target["type"] != "train":
                continue
            webhook_url = os.environ.get(target["webhook_env"])
            if not webhook_url:
                continue
            send_discord(
                f"🚆 **{target['name']} 通知**\n\n⚪ 查無資料（TDX token 錯誤：{e}）",
                webhook_url,
            )
        return

    # [TEMP: SD-4 之前的暫時方案] 用 TARGET_NAME env 過濾要跑的 target，
    # 讓不同 cron 可以各自觸發單一 target。SD-4 完成後可整段移除。
    target_filter = os.environ.get("TARGET_NAME")
    targets = NOTIFY_TARGETS
    if target_filter:
        targets = [t for t in NOTIFY_TARGETS if t["name"] == target_filter]
        if not targets:
            print(f"no target matches TARGET_NAME={target_filter}")
            return

    for target in targets:
        process_target(target, token)


if __name__ == "__main__":
    main()
