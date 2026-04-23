# 🎥 MissAV Downloader Web UI

A **MissAV web-based downloader** that works perfectly in TrueNAS and Docker environments.
Built with `curl_cffi` and `yt-dlp` to bypass ISP blocking (SNI) and Cloudflare's strong bot protection.

## ✨ Features

### Core Features

- **Web UI:** Simply enter a URL in your browser — downloads run smoothly in the background.
- **Real-time Progress Display:** Monitor download progress (%) with an intuitive green gauge bar — no need to check the terminal.
- **Smart Bypass Logic:**
  - Uses `curl_cffi` to impersonate the latest Chrome browser, bypassing Cloudflare bot protection and CAPTCHA.
  - Automatically rotates through MissAV's mirror domains to find an accessible address.
- **Full VPN Compatibility:** Works seamlessly even when attached to a VPN container network like Gluetun, correctly bypassing IP restrictions.
- **Enhanced Stability:** Automatically optimizes filenames to prevent filesystem save errors (`[Errno 36] File name too long`) caused by long Japanese/Korean titles.
- **Cancel Task Function:** Click the `Delete` button in the list to immediately force-terminate (cancel) the background download process.

### New Features

- **🌍 Multilingual Support:** Available in English, Korean, Japanese, and Chinese (Simplified). Easily switch languages via the dropdown menu.
- **⚙️ Settings Management:** Configure download directory, sequential mode, delay between downloads, default quality, and mirror domains directly from the web UI.
- **🔍 JAV Code Conversion:** Simply enter a JAV code (e.g., ABP-123) and the app automatically converts it to the correct MissAV URL.
- **📦 Batch Download:** Add multiple URLs or JAV codes at once for bulk downloading.
- **📁 File Manager:** Browse, search, preview, and delete downloaded files directly from the web interface.
- **📝 Download Logs:** Each download task has its own log file for troubleshooting.
- **⚡ Sequential/Parallel Mode:** Choose between downloading one video at a time or multiple concurrently.

## 🛠️ Installation & Usage

> ⚠️ **Recommendation:** For safety, run this with a VPN (e.g., Gluetun).

### 1. Create `docker-compose.yml`

Attach the downloader container to the VPN network. (Uses GitHub Container Registry.)

```yaml
version: '3'
services:
  missav-dlp-web:
    image: ghcr.io/nerdnam/missav-dlp-web:latest
    network_mode: "container:gluetun-vpn" # Optional: when using a VPN container
    # ports:
    #   - "5000:5000" # Only enable if NOT using a VPN
    volumes:
      - /path/to/your/downloads:/downloads
      - ./locales:/app/locales # Optional: for custom translations
    restart: unless-stopped
```

### 2. Add Port to Gluetun `docker-compose.yml`

Since the downloader attaches to the VPN container, you **must** add the external access port to the **Gluetun container configuration**:

```yaml
services:
  gluetun-vpn:
    # ... (existing Gluetun config) ...
    ports:
      - "58000:5000/tcp"  # Map host port 58000 to container port 5000
```

### 3. Access the Web UI

After starting the containers, open your browser and go to:

```
http://[YOUR_NAS_OR_SERVER_IP]:58000
```

## 📁 Project Structure

```
missav-dlp-web/
├── app.py                    # Main Flask application
├── .settings.json            # User settings (auto-generated)
├── downloads/                # Downloaded videos
├── logs/                     # Download task logs
├── locales/                  # Language files
│   ├── en.json              # English
│   ├── ko.json              # Korean
│   ├── ja.json              # Japanese
│   └── zh.json              # Chinese (Simplified)
├── templates/                # Web interface
│   ├── index.html           # Main page
│   ├── script.js            # Frontend logic
│   └── style.css            # Styles
├── app_files/               # Backend modules
│   ├── config_manager.py    # Settings management
│   ├── download_manager.py  # Download queue & yt-dlp
│   ├── extractor.py         # Custom MissAV extractor
│   ├── language.py          # Multilingual support
│   ├── paths.py             # Path management
│   └── utils.py             # Helper functions
└── ffmpeg/                  # FFmpeg binaries (optional)
    └── bin/
        └── ffmpeg.exe
```

## 🌍 Language Support

The application supports multiple languages that can be switched at any time:

| Language                  | Code | Status  |
| ------------------------- | ---- | ------- |
| English                   | en   | ✅ Full |
| 한국어 (Korean)           | ko   | ✅ Full |
| 日本語 (Japanese)         | ja   | ✅ Full |
| 中文 (Chinese Simplified) | zh   | ✅ Full |

To add a new language:

1. Create a new JSON file in the `locales/` folder (e.g., `fr.json`)
2. Copy the structure from `en.json` and translate the values
3. Add the language code to the dropdown in `templates/index.html`

## ⚙️ Configuration

Settings are stored in `.settings.json` and can be modified via the web UI:

| Setting                 | Description                        | Default                             |
| ----------------------- | ---------------------------------- | ----------------------------------- |
| Download Directory      | Where videos are saved             | `./downloads`                     |
| Sequential Mode         | Download one video at a time       | `true`                            |
| Delay Between Downloads | Seconds to wait between downloads  | `3`                               |
| Default Quality         | Maximum resolution to download     | `best`                            |
| Mirror Domains          | MissAV mirror domains for fallback | `missav.ai`, `missav.net`, etc. |

### Advanced Configuration

You can also edit `.settings.json` directly:

```json
{
  "max_concurrent": 1,
  "filename_template": "[%(id)s] %(title).60s.%(ext)s",
  "spoofdpi_enabled": true,
  "video_quality": "best",
  "mirrors": ["missav.ai", "missav.net", "missav123.com", "missav.com", "missav.ws"],
  "download_dir": "./downloads",
  "delay_between_downloads": 3,
  "max_retries": 3,
  "sequential_mode": true
}
```

## 🚀 Usage Examples

### Single Download

1. Enter a MissAV URL or JAV code (e.g., `ABP-123`)
2. Click "Get Info" to fetch video details
3. Select quality preference
4. Click "Download Now" or "Add to Queue"

### Batch Download

1. Click "Batch Add"
2. Enter multiple URLs or JAV codes (one per line)
3. Click "Add All to Queue"

### Managing Downloads

- View real-time progress in the queue
- Cancel individual downloads with the ✕ button
- Clean completed tasks or clear waiting queue
- Browse and manage downloaded files in the Downloads section

## 🔧 Troubleshooting

| Issue                 | Solution                                                                  |
| --------------------- | ------------------------------------------------------------------------- |
| Can't access Web UI   | Check that the port is correctly exposed in the Gluetun container         |
| Downloads stuck       | Verify VPN connection and network mode configuration                      |
| File name errors      | The tool auto-shortens filenames — ensure your download path is writable |
| Settings not saving   | Check write permissions for `.settings.json` in the root directory      |
| Language not changing | Clear browser cache or check if `locales/` folder is properly mounted   |
| JAV code not working  | Ensure format is correct (e.g.,`ABP-123`, `SSIS-456`)                 |

## 🐳 Docker Build

To build the Docker image locally:

```bash
docker build -t missav-dlp-web .
docker run -p 5000:5000 -v $(pwd)/downloads:/downloads missav-dlp-web
```

## 📦 Requirements

- Docker & Docker Compose
- (Optional) Gluetun or any OpenVPN/WireGuard container
- Python 3.8+ (for local development)
- FFmpeg (for video merging)

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

# Access at http://localhost:5000
```

## 🔄 API Endpoints

The application provides REST API endpoints:

| Endpoint             | Method   | Description            |
| -------------------- | -------- | ---------------------- |
| `/api/info`        | POST     | Get video information  |
| `/api/download`    | POST     | Add single download    |
| `/api/batch`       | POST     | Add multiple downloads |
| `/api/tasks`       | GET      | List all tasks         |
| `/api/tasks/<id>`  | DELETE   | Cancel task            |
| `/api/queue/stats` | GET      | Queue statistics       |
| `/api/settings`    | GET/PUT  | Get/Update settings    |
| `/api/files`       | GET      | List downloaded files  |
| `/api/language`    | GET/POST | Get/Set language       |

## ⚠️ Disclaimer

This tool is for **personal use only**. The user is solely responsible for copyright compliance and any consequences arising from downloaded content.

## 📄 License

MIT License - see [LICENSE](LICENSE) file

## 🙏 Acknowledgments

This project is based on the excellent work by **[nerdnam](https://github.com/nerdnam)** and the original **[missav-dlp-web](https://github.com/nerdnam/missav-dlp-web)** repository.

### Original Repository

- **Author:** nerdnam
- **Repository:** [github.com/nerdnam/missav-dlp-web](https://github.com/nerdnam/missav-dlp-web)
- **License:** Check the original repository for licensing terms

### Key Features Used/Adapted

- `curl_cffi` + `yt-dlp` integration for Cloudflare bypass
- Mirror domain rotation logic
- VPN compatibility (Gluetun)
- Web-based download UI with real-time progress

### Additional Improvements

- Multilingual support (4 languages)
- Settings management UI
- JAV code converter
- Batch download functionality
- File manager with search & preview
- Task-specific logging
- Sequential/Parallel download modes

### Thanks To

- All contributors of the original project
- The open-source community for `yt-dlp` and `curl_cffi`
- Translators who helped with localization

---

## 📝 Changelog

### Version 3.0

- Added multilingual support (EN, KO, JA, ZH)
- Added settings management UI
- Added JAV code conversion
- Added batch download functionality
- Added file manager with search
- Added task-specific logging
- Reorganized code into `app_files/` module
- Fixed folder structure (downloads/logs in root)

### Version 2.0

- Initial release based on nerdnam's work
- Basic download functionality
- Real-time progress display
- Cloudflare bypass with curl_cffi
