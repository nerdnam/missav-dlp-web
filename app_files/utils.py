import re
import os
from pathlib import Path

def is_jav_code(text):
    pattern = re.compile(r'^([A-Z]{2,5})-(\d{3,5})$', re.IGNORECASE)
    return bool(pattern.match(text.strip().upper()))

def jav_code_to_url(code, mirror='missav.ws'):
    code = code.strip().upper()
    if is_jav_code(code):
        return f"https://{mirror}/ko/{code}"
    return None

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def format_size(bytes):
    if bytes >= 1_000_000_000:
        return f"{bytes / 1_000_000_000:.2f} GB"
    elif bytes >= 1_000_000:
        return f"{bytes / 1_000_000:.2f} MB"
    elif bytes >= 1_000:
        return f"{bytes / 1_000:.2f} KB"
    return f"{bytes} B"