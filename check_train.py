import requests
import os
from datetime import datetime

# 設定
TDX_CLIENT_ID = os.environ["TDX_CLIENT_ID"]
TDX_CLIENT_SECRET = os.environ["TDX_CLIENT_SECRET"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

TRAIN_NOS = ["2124", "1152"]
STATION_ID = "QZK"  # 崎頂站代碼

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

def main():
    today = datetime.now().weekday()
    if today >= 5:  # 週六、週日跳過
        print("今天是假日，不發送通知")
        return

    token = get_tdx_token()
    delays = get_delay_info(token)

    # 建立車次誤點查詢表
    delay_map = {}
    for d in delays:
        train_no = d.get("TrainNo")
        if train_no in TRAIN_NOS:
            delay_map[train_no] = d.get("DelayTime", 0)

    train_info = {
        "2124": "08:02",
        "1152": "08:14",
    }

    lines = ["🚆 **今日崎頂出發火車誤點通知**\n"]
    for train_no, depart_time in train_info.items():
        delay = delay_map.get(train_no)
        if delay is None:
            status = "⚪ 查無資料"
        elif delay == 0:
            status = "✅ 準點"
        else:
            status = f"⚠️ 誤點 **{delay} 分鐘**"
        lines.append(f"**{train_no} 次**（{depart_time} 崎頂發）：{status}")

    message = "\n".join(lines)
    send_discord(message)
    print(message)

if __name__ == "__main__":
    main()
