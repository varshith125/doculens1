# Deploying DocuLens on Oracle Cloud (Always Free)

Runs the published image `varshith6166/doculens` behind Caddy, which provides HTTPS
automatically.

## Before you start

1. An Oracle Cloud **Ampere VM.Standard.A1.Flex** server (Always Free eligible),
   Ubuntu 24.04, with a public IP. 4 OCPU / 24 GB is comfortable; 2 OCPU / 12 GB also works.
2. Ports **80** and **443** open in the subnet's Security List (ingress, TCP, source `0.0.0.0/0`).
3. A domain name pointing to the server's public IP, for example a free
   [DuckDNS](https://www.duckdns.org) subdomain.

## Install

Connect to the server and run the setup script with your domain:

```bash
ssh -i path/to/private.key ubuntu@SERVER_IP
curl -fsSL https://raw.githubusercontent.com/varshith125/doculens1/main/deploy/oracle/setup.sh | bash -s -- yourname.duckdns.org
```

It installs Docker, opens ports 80 and 443 in the server's firewall, downloads
`docker-compose.yml` and `Caddyfile`, and starts the app. After a minute or two,
open `https://yourname.duckdns.org`.

## Everyday commands

```bash
cd ~/doculens
sudo docker compose ps            # status
sudo docker compose logs -f       # live logs (no document data is logged)
sudo docker compose pull && sudo docker compose up -d   # update to the newest image
sudo docker compose down          # stop
```

## Notes

- Scans are processed in memory and deleted as soon as the result is delivered; the
  application container has a read-only file system.
- Only Caddy's HTTPS certificates are stored on disk (in a Docker volume).
- Oracle may reclaim Always Free servers that stay almost completely idle for a long time.
