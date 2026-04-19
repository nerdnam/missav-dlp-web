# 🎥 MissAV Downloader Web UI

A **MissAV web-based downloader** that works perfectly in TrueNAS and Docker environments.
It is built by combining `curl_cffi` and `yt-dlp` to bypass ISP blocking (SNI) and Cloudflare's strong bot protection.

## ✨ Features

- **Web UI:** Just enter a URL in the browser, and the download will proceed in the background.
- **Real-time Progress Display:** You can check the download progress (%) with an intuitive green gauge bar on the web screen without needing to look at the terminal.
- **Perfect Bypass Logic:**
  - Utilizes `curl_cffi` to impersonate the latest Chrome browser, smoothly bypassing Cloudflare's bot protection and CAPTCHA.
  - Automatically rotates through MissAV's multiple mirror domains to find an accessible address on its own.
- **Full VPN Compatibility:** Even when attached to a VPN container network like Gluetun, it can correctly bypass IP restrictions and download.
- **Enhanced Stability:** Automatically optimizes filenames to prevent file system save errors (`[Errno 36] File name too long`) caused by long Japanese/Korean titles.
- **Cancel Task Function:** Clicking the `Delete` button in the list will immediately force-terminate (Cancel) the background download process.

## 🛠️ Installation & Usage

It is strongly recommended to run this safely with a VPN (e.g., Gluetun).

### 1. Create `docker-compose.yml`

Attach the downloader container to the VPN network. (Uses GitHub Container Registry.)

```yaml
version: '3'
services:
  missav-dlp-web:
    image: ghcr.io/nerdnam/missav-dlp-web:latest
    network_mode: "container:gluetun-vpn" # (Optional) When using a VPN container network
    # ports:
    #   - "5000:5000" # Only enable if not using a VPN.
    volumes:
      - /path/to/your/downloads:/downloads
    restart: unless-stopped
```

### 2. Add Port to Gluetun docker-compose.yml

Since the network is attached to the VPN container, the external access port **must** be added to the **Gluetun container configuration**:

```yaml
services:
  gluetun-vpn:
    # ... (existing Gluetun config) ...
    ports:
      - "58000:5000/tcp"  # Map host port 58000 to container port 5000
```

### 3. Access the Web UI

After running the container, access it from your browser at http://[NAS_OR_SERVER_IP]:58000.

## ⚠️ 면책 조항 (Disclaimer)

This tool is for personal use only. The responsibility for the copyright and use of the downloaded content lies entirely with the user.

```

```
