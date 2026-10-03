import os

from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

if not TMDB_API_KEY:
    raise RuntimeError("TMDB_API_KEY is not set. Copy .env.example to .env and fill it in.")

# Anthropic key is optional: without it, the app still runs using the
# keyword-based recommendation mode instead of Claude.
CLAUDE_AVAILABLE = bool(ANTHROPIC_API_KEY)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
WATCH_REGION = "US"

CLAUDE_MODEL = "claude-haiku-4-5"

PROVIDER_CACHE_TTL_SECONDS = 24 * 60 * 60
TITLE_PROVIDER_CACHE_TTL_SECONDS = 60 * 60

# TMDB's full watch-provider list includes hundreds of regional add-on/channel
# variants (e.g. "AMC+ Roku Premium Channel"). Curate down to the major
# services most users actually subscribe to, in display order.
MAJOR_PROVIDER_IDS = [
    8,     # Netflix
    15,    # Hulu
    337,   # Disney Plus
    1899,  # HBO Max
    9,     # Amazon Prime Video
    350,   # Apple TV
    386,   # Peacock Premium
    2303,  # Paramount Plus Premium
    43,    # Starz
    1768,  # ESPN Plus
]
