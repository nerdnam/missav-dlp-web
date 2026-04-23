from pathlib import Path

# Get the root directory (parent of app_files)
ROOT_DIR = Path(__file__).parent.parent

# Define all paths relative to root
DOWNLOADS_DIR = ROOT_DIR / 'downloads'
LOGS_DIR = ROOT_DIR / 'logs'
SETTINGS_FILE = ROOT_DIR / '.settings.json'
FFMPEG_DIR = ROOT_DIR / 'ffmpeg'