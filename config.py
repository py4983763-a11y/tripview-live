import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GPS_DATA_DIR = BASE_DIR
VIDEO_DIR = os.path.join(BASE_DIR, "preview_videos")
CACHE_DIR = os.path.join(BASE_DIR, "ai_cache")

USERS_FILE = os.path.join(BASE_DIR, "users.json")
MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")

# Detect if running on Render or Cloud Production server
IS_RENDER = os.environ.get("RENDER", "").lower() == "true"

# YOLO Model Configuration:
CUSTOM_MODEL_PATH = os.path.join(BASE_DIR, "best.pt")
DEFAULT_MODEL_NAME = "yolo26n.pt"
FALLBACK_MODEL_NAME = "yolo11n.pt"

# Optimized for fast CPU + GPU frame-by-frame detection & Render 512MB RAM safety
YOLO_CONF_THRESHOLD = 0.28
YOLO_IOU_THRESHOLD = 0.45
YOLO_IMG_SIZE = 416 if IS_RENDER else 640
SAMPLE_FPS = 1 if IS_RENDER else 2
ENABLE_BACKGROUND_PREINDEX = not IS_RENDER

SECRET_KEY = os.environ.get("TRIPVIEW_SECRET", "tripview_prod_secret_2026")

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)