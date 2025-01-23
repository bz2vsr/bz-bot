import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

API_URL = "https://multiplayersessionlist.iondriver.com/api/1.0/sessions?game=bigboat:battlezone_combat_commander" 

MONITORED_STEAM_IDS = [
    "76561199653748651",  # Sev
    "76561198058690608",  # JudgeGuns
    "76561197974548434",  # VTrider
    "76561198846500539",  # Xohm
    "76561198006115793",  # Domakus
    "herpmcderperson",    # Herp
    "76561198088036138",  # dd
    "76561198820311491",  # m.s 
    "76561198825004088",  # Lamper
    "76561198026325621",  # F9Bomber
    "bz2Cyber",           # Cyber
    # "XXX", # Sly
    # "XXX", # Econchump
    # "76561198064801924",  # HappyOtter
    # "76561198045619216",  # Zack
    # "76561197970538803",  # Graves
    # "76561198345909972",  # Vivify
]

CHECK_INTERVAL = 15