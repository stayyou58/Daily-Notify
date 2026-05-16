NOTIFY_TARGETS = [
    {
        "name": "self",
        "type": "train",
        "from_station": "1230",  # 崎頂
        "trains": ["2124", "1152"],
        "webhook_env": "DISCORD_WEBHOOK_URL_SELF",
    },
    {
        "name": "family_a",
        "type": "train",
        "from_station": "3260",  # 頭家厝
        "trains": ["2128"],
        "webhook_env": "DISCORD_WEBHOOK_URL_FAMILY_A",
    },
    {
        "name": "family_b",
        "type": "weather",
        "webhook_env": "DISCORD_WEBHOOK_URL_FAMILY_B",
    },
]
