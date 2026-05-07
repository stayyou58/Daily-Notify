import requests
import os
from datetime import datetime, timedelta, timezone

TW_TZ = timezone(timedelta(hours=8))

TDX_CLIENT_ID = os.environ["TDX_CLIENT_ID"]
TDX_CLIENT_SECRET = os.environ["TDX_CLIENT_SECRET"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

TRAIN_NOS = ["2124", "1152"]

def get_tdx_token():
    url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": TDX_CLIENT_ID,
        "client_secret": TDX_CLIENT_SECRET,
    }
    res = requests.post(url, data=data)
    return res.json()["access_token"]

def get_delay_info(token):
    url = "https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/LiveTrainDelay?%24format=JSON"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers)
    return res.json().get("TrainLiveDelays", [])

def get_train_timetable(token, train_no):
    """取得今日該車次完整停靠站時刻"""
    url = f"https://tdx.transportdata.tw/api/basic/v3/Rail/TRA/DailyTimetable/Today/TrainNo/{train_no}?%24format=JSON"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers)
    data = res.json()
    timetables = data.get("DailyTimetables", [])
    if not timetables:
        return []
    return timetables[0].get("StopTimes", [])

def get_current_station(stop_times, delay_minutes):
    """根據現在時間 + 誤點分鐘，推算火車目前停留的最後一站"""
    now = datetime.now(TW_TZ)
    delay = timedelta(minutes=delay_minutes)
    current_station = None

    for stop in stop_times:
        time_str = stop.get("DepartureTime") or stop.get("ArrivalTime")
        if not time_str:
            continue
        h, m = map(int, time_str.split(":"))
        actual_dt = now.replace(hour=h, minute=m, second=0, microsecond=0) + delay
        if now >= actual_dt:
            current_station = stop.get("StationName", {}).get("Zh_tw")
        else:
            break

    return current_station

def is_completed(stop_times, delay_minutes):
    """判斷火車是否已抵達末站完成運行"""
    if not stop_times:
        return False
    now = datetime.now(TW_TZ)
    last_stop = stop_times[-1]
    time_str = last_stop.get("ArrivalTime") or last_stop.get("DepartureTime")
    if not time_str:
        return False
    h, m = map(int, time_str.split(":"))
    final_dt = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=delay_minutes)
    return now > final_dt

def get_status(train_no, delay_map, depart_time_str, stop_times):
    now = datetime.now(TW_TZ)
    h, m = map(int, depart_time_str.split(":"))
    depart_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)

    delay_minutes = delay_map.get(train_no) or 0

    # 情況一：已抵達末站，完成全程運行
    if is_completed(stop_times, delay_minutes):
        return "⬛ 已完駛"

    # 情況二：已離開崎頂站，顯示目前位置
    if now >= depart_dt:
        current_station = get_current_station(stop_times, delay_minutes)
        station_str = f"目前在 **{current_station}**" if current_station else "位置未知"
        if delay_minutes > 0:
            return f"🚂 已離開崎頂站，{station_str}，誤點 **{delay_minutes} 分鐘**"
        else:
            return f"🚂 已離開崎頂站，{station_str}，無誤點"

    # 情況三：尚未發車
    if delay_minutes > 0:
        return f"⚠️ 誤點 **{delay_minutes} 分鐘**"
    return "✅ 無誤點"

def send_discord(message):
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message})

def main():
    today = datetime.now(TW_TZ).weekday()  # 修正時區 bug
    if today >= 5:
        print("今天是假日，不發送通知")
        return

    try:
        token = get_tdx_token()
        delays = get_delay_info(token)
    except Exception as e:
        send_discord(f"🚆 **今日崎頂出發火車誤點通知**\n\n⚪ 查無資料（API 錯誤：{e}）")
        return

    delay_map = {}
    for d in delays:
        train_no = d.get("TrainNo")
        if train_no in TRAIN_NOS:
            delay_map[train_no] = d.get("DelayTime", 0)

    train_info = {"2124": "08:02", "1152": "08:14"}

    lines = ["🚆 **今日崎頂出發火車誤點通知**\n"]
    for train_no, depart_time in train_info.items():
        stop_times = get_train_timetable(token, train_no)
        status = get_status(train_no, delay_map, depart_time, stop_times)
        lines.append(f"**{train_no} 次**（{depart_time} 崎頂發）：{status}")

    message = "\n".join(lines)
    send_discord(message)
    print(message)

if __name__ == "__main__":
    main()