# 🎥 MissAV Downloader Web UI

TrueNAS 및 Docker 환경에서 동작하는 **MissAV 웹 기반 다운로더**입니다.
통신사 차단(SNI)과 Cloudflare 봇 차단을 우회하기 위해 `curl_cffi` + `yt-dlp` + **FlareSolverr**를 결합했습니다.

## ✨ 주요 기능 (Features)
- **웹 기반 UI:** 브라우저에서 URL만 입력하면 백그라운드로 다운로드가 진행됩니다.
- **실시간 진행률:** 초록색 게이지 바로 다운로드 진행률(%)을 표시합니다.
- **Cloudflare 봇 차단 우회:** 영상 CDN(surrit.com)은 자동화 요청(curl/yt-dlp)을 봇으로 판정해 차단합니다. 직접 요청이 막히면 **FlareSolverr(헤드리스 실제 브라우저)** 로 `cf_clearance` 쿠키를 받아, 그 쿠키로 영상 세그먼트를 받습니다 (쿠키 15분 캐시).
- **여러 미러 도메인 자동 인식:** `missav.ws / .ai / .live / .fans / .media / missav123.com / missav01.com` 등.
- **↻ 재시작 버튼:** 실패/취소된 작업을 같은 URL로 즉시 재시도합니다.
- **작업 취소:** 진행 중인 다운로드를 즉시 강제 종료합니다.
- **파일명 자동 최적화:** 긴 일본어/한국어 제목으로 인한 저장 에러(`[Errno 36] File name too long`)를 방지합니다.

## 🧩 구성요소 (Architecture)
정상 동작하려면 **세 가지가 같은 VPN 망**에 있어야 합니다:
1. **missav-dlp-web** — 다운로더 본체.
2. **FlareSolverr** — Cloudflare 통과용 헤드리스 브라우저. 다운로더와 **같은 Gluetun 망**(`network_mode: container:gluetun-vpn`)에 있어야 `cf_clearance` 쿠키가 같은 출구 IP로 발급됩니다. **(필수)**
3. **Gluetun VPN** — 단, **surrit.com에 밴되지 않은 출구 IP**여야 합니다. (아래 ⚠️ 참고)

## 🛠️ 설치 (Installation)

### 1. `docker-compose.yml`
```yaml
services:
  missav-dlp-web:
    image: ghcr.io/nerdnam/missav-dlp-web:0.0.7
    network_mode: "container:gluetun-vpn"
    restart: unless-stopped
    pull_policy: always
    volumes:
      - /실제/다운로드/경로:/downloads

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    network_mode: "container:gluetun-vpn"   # 다운로더와 동일한 VPN IP 공유 (필수)
    restart: unless-stopped
    environment:
      - LOG_LEVEL=info
```
> 두 컨테이너가 같은 네트워크 네임스페이스라, 다운로더는 FlareSolverr를 `http://localhost:8191`로 자동 인식합니다. 다른 구성이라면 다운로더에 `FLARESOLVERR_URL` 환경변수로 지정하세요.

### 2. Gluetun에 포트 노출
네트워크가 VPN 컨테이너에 종속되므로, 외부 접속 포트는 반드시 **Gluetun 컨테이너 설정**에 추가합니다.
```yaml
services:
  gluetun-vpn:
    # ... (기존 Gluetun 설정) ...
    ports:
      - "58000:5000/tcp"  # 외부 58000 → 다운로더 내부 5000
```

### 3. 접속
브라우저에서 `http://[NAS_또는_서버_IP]:58000` 으로 접속합니다.

## ⚠️ 매우 중요 — VPN 출구 IP 설정
surrit.com(영상 CDN)의 Cloudflare는 **상용 VPN IP를 광범위하게 차단**하며, **IPv6로는 거의 항상 차단**됩니다. 두 가지를 꼭 지키세요.

**1) VPN을 IPv4 전용으로** — WireGuard 설정에서 IPv6를 제거합니다.
- `Address`에서 IPv6(`...::.../128`) 삭제 → `Address = 10.2.0.2/32`
- `AllowedIPs`에서 `::/0` 삭제 → `AllowedIPs = 0.0.0.0/0`

서버가 IPv6로 나가면 그 대역이 차단되어 다운로드가 실패합니다.

**2) 밴되지 않은 서버를 사용** — 일부 VPN 서버는 surrit.com에 밴되어 있어 FlareSolverr(진짜 브라우저)로도 통과하지 못합니다.
- **브라우저에서 직접 영상이 재생/다운로드되는 바로 그 서버**를 Gluetun에도 사용하세요.
- 막히면 다른 서버로 교체하면 됩니다(코드·FlareSolverr는 그대로).

## 🩺 문제 해결 (Troubleshooting)
- **`[FlareSolverr] 실패: ... IP is banned`** → 현재 VPN 출구 IP가 밴됨. **다른 VPN 서버**로 교체(IPv4 전용 유지). 브라우저에서 실제로 되는 서버를 고르세요.
- **`[FlareSolverr] 호출 실패`** → FlareSolverr 컨테이너가 안 떴거나 주소가 틀림. 같은 Gluetun 망에 있는지 확인.
- **작업이 에러로 끝남** → 작업 카드의 `↻ 재시작` 버튼으로 재시도(일시적 차단/네트워크 blip에 효과적).
- **이미지가 안 바뀜(코드 반영 안 됨)** → Docker 태그 캐시 때문입니다. compose 이미지를 **새 태그**(예: `:0.0.7`)로 지정하고 `docker compose pull` 후 `docker compose up -d`.

## ⚠️ 면책 조항 (Disclaimer)
이 도구는 개인적인 용도로만 사용해야 하며, 다운로드한 콘텐츠의 저작권 및 사용에 대한 책임은 전적으로 사용자 본인에게 있습니다.
