import requests
import os
from datetime import datetime, timedelta

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

def send_discord(message):
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message})

def get_status(train_no, delay_map, depart_time_str):
    now = datetime.now()
    h, m = map(int, depart_time_str.split(":"))
    depart_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)

    delay = delay_map.get(train_no)

    if delay is not None and delay > 0:
        return f"⚠️ 誤點 **{delay} 分鐘**"

    if now >= depart_dt + timedelta(minutes=30):
        return "⬛ 已完駛"

    return "✅ 無誤點"

def main():
    today = datetime.now().weekday()
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
        status = get_status(train_no, delay_map, depart_time)
        lines.append(f"**{train_no} 次**（{depart_time} 崎頂發）：{status}")

    message = "\n".join(lines)
    send_discord(message)
    print(message)

if __name__ == "__main__":
    main()
