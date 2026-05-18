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


def get_all_live_boards(token):
    """一次取得全線即時看板，回傳 {train_no: board}。全站共用，只需打一次。"""
    url = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/TrainLiveBoard?%24format=JSON"
    boards = tdx_get(url, token).get("TrainLiveBoards", [])
    return {b.get("TrainNo"): b for b in boards}


def get_station_timetable(token, station_id):
    """一次取得該站今日所有車次停靠時刻，回傳 ({train_no: stop}, station_name)。"""
    url = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyStationTimetable/Today/Station/{station_id}?%24format=JSON"
    data = tdx_get(url, token)
    stops = {}
    station_name = None
    for group in data.get("StationTimetables", []):
        if station_name is None:
            station_name = group.get("StationName", {}).get("Zh_tw")
        for stop in group.get("TimeTables", []):
            stops[stop.get("TrainNo")] = stop
    return stops, station_name


def get_stop_time(stop):
    """取得該站的發車時間，若無則退而取到站時間"""
    return stop.get("DepartureTime") or stop.get("ArrivalTime")


def get_status(live_board, depart_time, from_station_name):
    now = datetime.now(TW_TZ)
    h, m = map(int, depart_time.split(":"))
    scheduled_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if live_board is None:
        # 無即時看板：發車前視為尚未發車，發車後視為已離站（站別時刻表拿不到末站時間，無法判定完駛）
        if now < scheduled_dt:
            return "⏳ 尚未發車"
        return "⬛ 已發車（無即時位置資訊）"

    delay_minutes = live_board.get("DelayTime", 0)
    depart_dt = scheduled_dt + timedelta(minutes=delay_minutes)

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


def build_train_message(target, token, live_boards):
    from_station_id = target["from_station"]
    trains = target["trains"]

    # 每個出發站只打一次站別時刻表；即時看板由外部共用傳入。
    station_timetable, station_name = get_station_timetable(token, from_station_id)
    from_station_name = station_name or from_station_id

    train_status_lines = []
    for train_no in trains:
        stop = station_timetable.get(train_no)
        depart_time = get_stop_time(stop) if stop else None

        if not depart_time:
            train_status_lines.append(f"**{train_no} 次**：⚪ 查無起站資訊")
            continue

        live_board = live_boards.get(train_no)
        status = get_status(live_board, depart_time, from_station_name)
        train_status_lines.append(
            f"**{train_no} 次**（{depart_time} {from_station_name}發）：{status}"
        )

    lines = [f"🚆 **今日{from_station_name}出發火車誤點通知**\n"] + train_status_lines
    return "\n".join(lines)


def process_target(target, token, live_boards):
    webhook_url = os.environ.get(target["webhook_env"])
    if not webhook_url:
        print(f"skip {target['name']}: env {target['webhook_env']} not set")
        return

    if target["type"] != "train":
        # 非 train 類型（如 weather）目前還沒實作
        print(f"skip {target['name']}: type={target['type']} not yet supported")
        return

    try:
        message = build_train_message(target, token, live_boards)
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

    # 即時看板全站共用，整輪只抓一次
    live_boards = get_all_live_boards(token)

    for target in targets:
        process_target(target, token, live_boards)


if __name__ == "__main__":
    main()
