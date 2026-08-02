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
PROJECT_CATEGORY_ID = int(os.getenv("PROJECT_CATEGORY_ID", "1524467630868664371"))
NEW_PROJECT_CHANNEL_ID = int(os.getenv("NEW_PROJECT_CHANNEL_ID", "1524467686665621607"))
UPDATE_PROJECT_CHANNEL_ID = int(os.getenv("UPDATE_PROJECT_CHANNEL_ID", "1524467702960488470"))
PROJECT_DROP_CHANNEL_ID = int(os.getenv("PROJECT_DROP_CHANNEL_ID", "1524467707079163908"))
PROJECT_PUBLIC_URL = os.getenv("PROJECT_PUBLIC_URL", "https://ryukomik.my.id").rstrip("/")
PROJECT_EVENTS_URL = os.getenv("PROJECT_EVENTS_URL", "https://ryukomik.my.id/api/internal/project-discord-events")
PROJECT_EVENTS_TOKEN = os.getenv("PROJECT_EVENTS_TOKEN", "")

# Role IDs
ROLE_STAFF_ID = int(os.getenv("ROLE_STAFF_ID", "1524458627124166696"))
ROLE_ADMIN_ID = int(os.getenv("ROLE_ADMIN_ID", "1524457168072343762"))

# API
ASURA_API = os.getenv("ASURA_API", "https://api.ryukomik.web.id/asura")
DOUJIVA_API = os.getenv("DOUJIVA_API", "https://api.ryukomik.web.id/doujiva")
OMEGA_API = os.getenv("OMEGA_API", "https://api.ryukomik.web.id/omega")
EVASCAN_API = os.getenv("EVASCAN_API", "https://api.ryukomik.web.id/evascan")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://staff.ryukomik.web.id")

