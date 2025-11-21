# The Digital Bookshelf

A unified reading platform combining **Calibre-Web** (ebook management) with **Wallabag** (read-it-later articles) integration.

## Overview

The Digital Bookshelf allows you to:
- Browse and read your ebook library (Calibre-Web)
- View and manage saved web articles (Wallabag integration)
- Export articles as EPUB/PDF/MOBI to your ebook library
- Have a single interface for all your reading materials

## Architecture

```
+-------------------+          +-------------------+
|   Calibre-Web     |  <--->   |    Wallabag       |
|   (Flask/Python)  |   API    |   (PHP/Symfony)   |
+-------------------+          +-------------------+
        |                              |
        v                              v
+-------------------+          +-------------------+
|  Calibre Library  |          |  Wallabag DB      |
|    (SQLite)       |          |  (MySQL/SQLite)   |
+-------------------+          +-------------------+
```

## Requirements

### For Calibre-Web
- Python 3.6+
- SQLite (for app database)
- Calibre library (optional, for ebook management)

### For Wallabag
- PHP 7.4+ / PHP 8.x
- MySQL/MariaDB or PostgreSQL or SQLite
- Composer
- Web server (Apache/Nginx)

## Installation

### 1. Install Wallabag

#### Using Docker (Recommended)

```bash
docker run -d \
  --name wallabag \
  -p 8080:80 \
  -e SYMFONY__ENV__DOMAIN_NAME=http://localhost:8080 \
  -e SYMFONY__ENV__DATABASE_DRIVER=pdo_sqlite \
  -e SYMFONY__ENV__DATABASE_NAME=wallabag \
  -v /path/to/data:/var/www/wallabag/data \
  -v /path/to/images:/var/www/wallabag/web/assets/images \
  wallabag/wallabag
```

#### Manual Installation

```bash
cd wallabag-master
composer install
php bin/console wallabag:install --env=prod
```

Default credentials: `wallabag` / `wallabag`

### 2. Install Calibre-Web

```bash
cd calibre-web

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run
python cps.py
```

Access at: `http://localhost:8083`
Default credentials: `admin` / `admin123`

### 3. Configure Wallabag API Access

1. Log in to your Wallabag instance
2. Go to **Config** > **API clients management** (or `/developer`)
3. Click **Create a new client**
4. Fill in:
   - Name: `Calibre-Web` (or any name)
   - Redirect URIs: leave empty or add your callback URL
5. Save and copy the **Client ID** and **Client Secret**

### 4. Connect Calibre-Web to Wallabag

1. Log in to Calibre-Web
2. Go to **Articles** > **Settings** (or navigate to `/wallabag/settings`)
3. Enter your Wallabag credentials:
   - **Server URL**: `http://localhost:8080` (your Wallabag URL)
   - **Client ID**: (from step 3)
   - **Client Secret**: (from step 3)
   - **Username**: Your Wallabag username
   - **Password**: Your Wallabag password
4. Enable the integration and save
5. Test the connection

## Usage

### Viewing Articles

Navigate to `/wallabag` in Calibre-Web to:
- View unread articles
- Browse archived articles
- View starred articles
- Filter by tags

### Adding Articles

1. **From Calibre-Web**: Click "Add Article" and paste a URL
2. **From Wallabag**: Use browser extensions, mobile apps, or bookmarklet
3. **Via API**: Send POST request to Wallabag API

### Exporting Articles

Articles can be exported to:
- **EPUB**: For e-readers
- **PDF**: For printing or archiving
- **MOBI**: For Kindle devices

Click the download button on any article to export.

## Docker Compose Setup

Create a `docker-compose.yml`:

```yaml
version: '3.8'

services:
  calibre-web:
    build: ./calibre-web
    ports:
      - "8083:8083"
    volumes:
      - ./calibre-library:/books
      - ./calibre-web-config:/config
    environment:
      - PUID=1000
      - PGID=1000
    depends_on:
      - wallabag
    restart: unless-stopped

  wallabag:
    image: wallabag/wallabag:latest
    ports:
      - "8080:80"
    environment:
      - SYMFONY__ENV__DOMAIN_NAME=http://localhost:8080
      - SYMFONY__ENV__DATABASE_DRIVER=pdo_sqlite
      - SYMFONY__ENV__DATABASE_NAME=wallabag
      - SYMFONY__ENV__FOSUSER_REGISTRATION=false
    volumes:
      - ./wallabag-data:/var/www/wallabag/data
      - ./wallabag-images:/var/www/wallabag/web/assets/images
    restart: unless-stopped

  # Optional: Use MySQL instead of SQLite for better performance
  # wallabag-db:
  #   image: mariadb:10
  #   environment:
  #     - MYSQL_ROOT_PASSWORD=wallabag
  #     - MYSQL_DATABASE=wallabag
  #     - MYSQL_USER=wallabag
  #     - MYSQL_PASSWORD=wallabag
  #   volumes:
  #     - ./wallabag-db:/var/lib/mysql
  #   restart: unless-stopped
```

Run with:
```bash
docker-compose up -d
```

## Configuration Reference

### Calibre-Web Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CALIBRE_DBPATH` | Path to Calibre library | `/books` |
| `APP_DB_PATH` | Path to app database | `./app.db` |

### Wallabag Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SYMFONY__ENV__DOMAIN_NAME` | Public URL | Required |
| `SYMFONY__ENV__DATABASE_DRIVER` | DB driver | `pdo_sqlite` |
| `SYMFONY__ENV__FOSUSER_REGISTRATION` | Allow registration | `true` |

## API Endpoints

### Wallabag Integration Routes (Calibre-Web)

| Route | Method | Description |
|-------|--------|-------------|
| `/wallabag` | GET | List articles |
| `/wallabag/article/<id>` | GET | View article |
| `/wallabag/article/<id>/archive` | POST | Toggle archive |
| `/wallabag/article/<id>/star` | POST | Toggle star |
| `/wallabag/article/<id>/delete` | POST | Delete article |
| `/wallabag/article/<id>/export/<format>` | GET | Export article |
| `/wallabag/add` | GET/POST | Add new article |
| `/wallabag/tags` | GET | List all tags |
| `/wallabag/tag/<slug>` | GET | Articles by tag |
| `/wallabag/settings` | GET/POST | Configure integration |
| `/wallabag/refresh` | GET | Refresh cache |
| `/wallabag/test` | GET | Test connection |

## Troubleshooting

### Connection Failed

1. Verify Wallabag URL is accessible
2. Check Client ID and Secret are correct
3. Ensure username/password are valid
4. Check Wallabag logs: `docker logs wallabag`

### Articles Not Loading

1. Try refreshing: `/wallabag/refresh`
2. Check Wallabag API status: `curl https://your-wallabag/api/version.json`
3. Verify OAuth tokens in Calibre-Web database

### Export Not Working

Wallabag must have export feature enabled:
1. Check Wallabag config: `app/config/parameters.yml`
2. Ensure `export_epub`, `export_pdf`, `export_mobi` are `true`

## Development

### File Structure

```
the-digital-bookshelf/
├── calibre-web/
│   ├── cps/
│   │   ├── services/
│   │   │   └── wallabag.py      # Wallabag API client
│   │   ├── wallabag.py          # Flask blueprint
│   │   ├── templates/
│   │   │   └── wallabag/        # Wallabag templates
│   │   ├── ub.py                # User database (WallabagConfig model)
│   │   └── main.py              # Blueprint registration
│   └── requirements.txt
├── wallabag-master/             # Wallabag source (PHP)
└── README.md
```

### Running Tests

```bash
cd calibre-web
python -m pytest tests/
```

## License

- Calibre-Web: GNU General Public License v3.0
- Wallabag: MIT License

## Credits

- [Calibre-Web](https://github.com/janeczku/calibre-web)
- [Wallabag](https://github.com/wallabag/wallabag)
