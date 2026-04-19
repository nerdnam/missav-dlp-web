
# 🎥 MissAV Downloader Web UI

A **MissAV web-based downloader** that works perfectly in TrueNAS and Docker environments.  
Built with `curl_cffi` and `yt-dlp` to bypass ISP blocking (SNI) and Cloudflare's strong bot protection.

## ✨ Features

- **Web UI:** Simply enter a URL in your browser — downloads run smoothly in the background.
- **Real-time Progress Display:** Monitor download progress (%) with an intuitive green gauge bar — no need to check the terminal.
- **Smart Bypass Logic:**
  - Uses `curl_cffi` to impersonate the latest Chrome browser, bypassing Cloudflare bot protection and CAPTCHA.
  - Automatically rotates through MissAV's mirror domains to find an accessible address.
- **Full VPN Compatibility:** Works seamlessly even when attached to a VPN container network like Gluetun, correctly bypassing IP restrictions.
- **Enhanced Stability:** Automatically optimizes filenames to prevent filesystem save errors (`[Errno 36] File name too long`) caused by long Japanese/Korean titles.
- **Cancel Task Function:** Click the `Delete` button in the list to immediately force-terminate (cancel) the background download process.

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

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| Can't access Web UI | Check that the port is correctly exposed in the Gluetun container |
| Downloads stuck | Verify VPN connection and network mode configuration |
| File name errors | The tool auto-shortens filenames — ensure your download path is writable |

## 📦 Requirements

- Docker & Docker Compose
- (Optional) Gluetun or any OpenVPN/WireGuard container

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

### Thanks To
- All contributors of the original project
- The open-source community for `yt-dlp` and `curl_cffi`

