import os
from dotenv import load_dotenv

load_dotenv()

# Discord Bot Token
TOKEN = os.getenv("DISCORD_TOKEN", "")

# Guild ID
GUILD_ID = int(os.getenv("GUILD_ID", "1524448659951849666"))

# Channel IDs
STAFF_TASKS_CHANNEL_ID = int(os.getenv("STAFF_TASKS_CHANNEL_ID", "1529129826558939268"))
STAFF_PAYRATE_CHANNEL_ID = int(os.getenv("STAFF_PAYRATE_CHANNEL_ID", "1524467683054325870"))
STAFF_LOG_CHANNEL_ID = int(os.getenv("STAFF_LOG_CHANNEL_ID", "1524468717591859234"))
REKRUT_CAT_ID = int(os.getenv("REKRUT_CAT_ID", "1524467626665836615"))

# Role IDs
ROLE_STAFF_ID = int(os.getenv("ROLE_STAFF_ID", "1524458627124166696"))
ROLE_ADMIN_ID = int(os.getenv("ROLE_ADMIN_ID", "1524457168072343762"))

# API
ASURA_API = os.getenv("ASURA_API", "https://api.ryukomik.web.id/asura")
