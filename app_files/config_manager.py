# app_files/config_manager.py

import os
import json
from pathlib import Path
from app_files.paths import SETTINGS_FILE, ROOT_DIR

DEFAULT_SETTINGS = {
    'max_concurrent': 1,
    'filename_template': '[%(id)s] %(title).60s.%(ext)s',
    'spoofdpi_enabled': True,
    'video_quality': 'best',
    'mirrors': ['missav.ai', 'missav.net', 'missav123.com', 'missav.com', 'missav.ws'],
    'download_dir': str(ROOT_DIR / 'downloads'),  # Changed to root
    'delay_between_downloads': 3,
    'max_retries': 3,
    'sequential_mode': True
}

def load_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                merged = DEFAULT_SETTINGS.copy()
                merged.update(saved)
                # Ensure mirrors is not empty
                if not merged.get('mirrors'):
                    merged['mirrors'] = DEFAULT_SETTINGS['mirrors']
                return merged
        except Exception as e:
            print(f"Error loading settings: {e}")
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving settings: {e}")