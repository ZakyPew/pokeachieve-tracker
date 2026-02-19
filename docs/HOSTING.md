# Hosting Requirements for PokeAchieve Platform 🎀

## Your Setup: Namecheap Domain + Cheap VPS

---

## Recommended VPS Providers (CHEAP!)

| Provider | Price | Specs | Why |
|----------|-------|-------|-----|
| **Vultr** | $5/mo | 1 CPU, 1GB RAM, 25GB SSD | Cheapest, reliable |
| **DigitalOcean** | $6/mo | 1 CPU, 1GB RAM, 25GB SSD | Popular, good docs |
| **Linode** | $5/mo | 1 CPU, 1GB RAM, 25GB SSD | Good support |
| **Hetzner** | €4.51/mo | 2 CPU, 4GB RAM, 40GB SSD | BEST VALUE (Europe) |

**My Recommendation:** Vultr or Hetzner (if you don't mind EU servers)

---

## Server Requirements

### Minimum Specs
- **OS:** Ubuntu 22.04 LTS (recommended)
- **RAM:** 1GB (2GB better)
- **CPU:** 1 vCPU
- **Storage:** 20GB SSD
- **Bandwidth:** 1TB/month (plenty)

### Software Stack
```bash
# System packages needed:
- Python 3.9+
- Node.js 18+
- Nginx (web server)
- Git
- SQLite (or PostgreSQL later)
- certbot (for SSL)
- pm2 or systemd (process manager)
```

---

## Step-by-Step Setup

### 1. Buy Domain (Namecheap)
- Buy your domain (e.g., pokeachieve.io)
- Point nameservers to your VPS or use Namecheap DNS

### 2. Point Domain to VPS
In Namecheap DNS:
```
Type: A Record
Host: @
Value: YOUR_VPS_IP
TTL: Automatic
```

Also add:
```
Type: A Record
Host: www
Value: YOUR_VPS_IP
```

### 3. Connect to VPS
```bash
ssh root@YOUR_VPS_IP
```

### 4. Initial Server Setup
```bash
# Update system
apt update && apt upgrade -y

# Install required packages
apt install -y python3-pip python3-venv nodejs npm nginx git certbot python3-certbot-nginx

# Create user (don't use root!)
adduser pokeachieve
usermod -aG sudo pokeachieve

# Switch to user
su - pokeachieve
```

### 5. Clone and Setup Backend
```bash
cd ~
git clone https://github.com/YOUR_USERNAME/pokeachieve-platform-private.git
cd pokeachieve-platform-private/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create database
python3 -c "from database import Base, engine; Base.metadata.create_all(bind=engine)"
```

### 6. Setup Systemd Service
```bash
sudo nano /etc/systemd/system/pokeachieve.service
```

Paste:
```ini
[Unit]
Description=PokeAchieve API
After=network.target

[Service]
User=pokeachieve
Group=pokeachieve
WorkingDirectory=/home/pokeachieve/pokeachieve-platform-private/backend
Environment="PATH=/home/pokeachieve/pokeachieve-platform-private/backend/venv/bin"
ExecStart=/home/pokeachieve/pokeachieve-platform-private/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable pokeachieve
sudo systemctl start pokeachieve
```

### 7. Build Frontend
```bash
cd ~/pokeachieve-platform-private/frontend
npm install
npm run build
```

### 8. Setup Nginx
```bash
sudo nano /etc/nginx/sites-available/pokeachieve
```

Paste:
```nginx
server {
    listen 80;
    server_name pokeachieve.io www.pokeachieve.io;

    # Frontend (static files)
    location / {
        root /home/pokeachieve/pokeachieve-platform-private/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/pokeachieve /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 9. SSL Certificate (HTTPS)
```bash
sudo certbot --nginx -d pokeachieve.io -d www.pokeachieve.io
```

Follow prompts. Certbot will auto-renew.

### 10. Firewall
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## Total Cost Breakdown

| Item | Monthly | Yearly |
|------|---------|--------|
| VPS (Vultr) | $5 | $60 |
| Domain (Namecheap) | ~$0.83 | $10 |
| **TOTAL** | **~$6** | **~$70** |

**To break even:** Need just 2 Pro subscribers ($5/month each)!

---

## Optional Upgrades (Later)

### PostgreSQL Database (instead of SQLite)
```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE DATABASE pokeachieve;"
sudo -u postgres psql -c "CREATE USER pokeachieve WITH PASSWORD 'yourpassword';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE pokeachieve TO pokeachieve;"
```

Update backend database URL.

### Redis (for caching/WebSocket)
```bash
sudo apt install redis-server
```

### Cloudflare (FREE CDN + DDoS protection)
1. Sign up at cloudflare.com
2. Add your domain
3. Change nameservers to Cloudflare
4. Get free SSL + faster global speeds

---

## Monitoring (Optional)

```bash
# Install pm2 for better process management
sudo npm install -g pm2

# Or use systemd (already setup above)

# View logs
sudo journalctl -u pokeachieve -f
```

---

## Backup Strategy

```bash
# Daily database backup
crontab -e

# Add:
0 2 * * * sqlite3 /path/to/pokeachieve.db ".backup '/backups/pokeachieve_$(date +\%Y\%m\%d).db'"
```

---

## Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't connect | Check firewall: `sudo ufw status` |
| 502 Bad Gateway | Check backend: `sudo systemctl status pokeachieve` |
| SSL not working | Run: `sudo certbot renew --dry-run` |
| Frontend not loading | Check nginx error: `sudo tail -f /var/log/nginx/error.log` |

---

Need help with any step, Daddy? 🎀
