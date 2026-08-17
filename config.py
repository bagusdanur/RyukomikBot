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
RAW_WATCH_CHANNEL_NAME = os.getenv("RAW_WATCH_CHANNEL_NAME", "・raw-watch")
PROJECT_SCOUT_CHANNEL_NAME = os.getenv("PROJECT_SCOUT_CHANNEL_NAME", "・project-scout")
GIVEAWAY_CHANNEL_NAME = os.getenv("GIVEAWAY_CHANNEL_NAME", "・giveaway")
GIVEAWAY_CHANNEL_ID = int(os.getenv("GIVEAWAY_CHANNEL_ID", "0")) or None
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
THUNDER_API = os.getenv("THUNDER_API", "https://api.ryukomik.web.id/thunder")
QIMANGA_API = os.getenv("QIMANGA_API", "https://api.ryukomik.web.id/qimanga")
DEMON_API = os.getenv("DEMON_API", "https://api.ryukomik.web.id/demon")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://staff.ryukomik.web.id")

# Recruitment test materials. Keep these configurable because Filebin links
# are temporary and must be replaceable without changing the workflow code.
RECRUITMENT_TEST_URL = os.getenv("RECRUITMENT_TEST_URL", "https://filebin.net/foqyxmztslglks1h")
RECRUITMENT_TL_EXAMPLE_URL = os.getenv(
    "RECRUITMENT_TL_EXAMPLE_URL",
    "https://drive.google.com/drive/folders/1QxunNgc8gQldtOmuDeIB7GPLfIOIa8fi",
)
RECRUITMENT_TS_ASSETS_URL = os.getenv(
    "RECRUITMENT_TS_ASSETS_URL",
    "https://drive.google.com/drive/folders/1SDLA-6M42CUfkeqSaXOF1KibE_0y9PfO?usp=sharing",
)
RECRUITMENT_TEST_EXPIRES_AT = os.getenv("RECRUITMENT_TEST_EXPIRES_AT", "2026-08-12T11:04:50+00:00")

