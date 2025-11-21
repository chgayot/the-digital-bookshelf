# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2024 Digital Bookshelf Contributors
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

"""
Wallabag API Client Service

This module provides integration with Wallabag (https://wallabag.org),
a self-hosted read-it-later application. It allows fetching articles
from a Wallabag instance and displaying them alongside ebooks in Calibre-Web.
"""

import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
import requests

from .. import logger

log = logger.create()

# Cache timeout for articles (5 minutes)
_CACHE_TIMEOUT = 5 * 60
_ARTICLES_CACHE = {}


class WallabagError(Exception):
    """Base exception for Wallabag API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class WallabagAuthError(WallabagError):
    """Authentication error with Wallabag API."""
    pass


class WallabagClient:
    """
    Client for interacting with the Wallabag API.

    Wallabag API Documentation: https://doc.wallabag.org/en/developer/api/readme.html
    """

    def __init__(self, host: str, client_id: str, client_secret: str,
                 username: str = None, password: str = None, access_token: str = None,
                 refresh_token: str = None):
        """
        Initialize Wallabag client.

        Args:
            host: Wallabag server URL (e.g., https://wallabag.example.com)
            client_id: OAuth2 client ID
            client_secret: OAuth2 client secret
            username: Wallabag username (for password grant)
            password: Wallabag password (for password grant)
            access_token: Existing access token (optional)
            refresh_token: Existing refresh token (optional)
        """
        self.host = host.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = 0

    @property
    def api_url(self) -> str:
        return f"{self.host}/api"

    def authenticate(self) -> Dict[str, Any]:
        """
        Authenticate with Wallabag using OAuth2 password grant.

        Returns:
            Dict containing access_token, refresh_token, expires_in
        """
        url = f"{self.host}/oauth/v2/token"
        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }

        try:
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()

            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = time.time() + expires_in - 60  # Refresh 1 min early

            log.info("Successfully authenticated with Wallabag")
            return token_data

        except requests.exceptions.HTTPError as e:
            log.error(f"Wallabag authentication failed: {e}")
            raise WallabagAuthError(f"Authentication failed: {e}",
                                   status_code=e.response.status_code if e.response else None)
        except requests.exceptions.RequestException as e:
            log.error(f"Wallabag connection error: {e}")
            raise WallabagError(f"Connection error: {e}")

    def refresh_access_token(self) -> Dict[str, Any]:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            return self.authenticate()

        url = f"{self.host}/oauth/v2/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }

        try:
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()

            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = time.time() + expires_in - 60

            log.debug("Wallabag access token refreshed")
            return token_data

        except requests.exceptions.HTTPError:
            # Refresh token expired, re-authenticate
            log.warning("Refresh token expired, re-authenticating")
            return self.authenticate()

    def _ensure_authenticated(self):
        """Ensure we have a valid access token."""
        if not self.access_token or time.time() >= self.token_expires_at:
            if self.refresh_token:
                self.refresh_access_token()
            else:
                self.authenticate()

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Make an authenticated request to the Wallabag API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint (e.g., /entries)
            **kwargs: Additional arguments passed to requests

        Returns:
            JSON response as dict
        """
        self._ensure_authenticated()

        url = f"{self.api_url}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)

            if response.status_code == 401:
                # Token might be invalid, try refreshing
                self.refresh_access_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                response = requests.request(method, url, headers=headers, timeout=30, **kwargs)

            response.raise_for_status()
            return response.json() if response.content else {}

        except requests.exceptions.HTTPError as e:
            log.error(f"Wallabag API error: {e}")
            raise WallabagError(f"API error: {e}",
                               status_code=e.response.status_code if e.response else None)
        except requests.exceptions.RequestException as e:
            log.error(f"Wallabag connection error: {e}")
            raise WallabagError(f"Connection error: {e}")

    def get_entries(self, archive: int = 0, starred: int = 0, sort: str = "created",
                    order: str = "desc", page: int = 1, per_page: int = 30,
                    tags: str = None, since: int = 0, public: int = None,
                    detail: str = "full") -> Dict[str, Any]:
        """
        Get entries (articles) from Wallabag.

        Args:
            archive: 0 = unread, 1 = archived, 2 = all
            starred: 0 = not starred, 1 = starred
            sort: Sort field (created, updated, archived)
            order: Sort order (asc, desc)
            page: Page number
            per_page: Number of entries per page (max 30)
            tags: Comma-separated list of tags
            since: Unix timestamp for entries since
            public: 0 = private, 1 = public
            detail: full or metadata

        Returns:
            Dict with _embedded.items containing entries
        """
        params = {
            "archive": archive,
            "starred": starred,
            "sort": sort,
            "order": order,
            "page": page,
            "perPage": per_page,
            "detail": detail,
        }

        if tags:
            params["tags"] = tags
        if since > 0:
            params["since"] = since
        if public is not None:
            params["public"] = public

        return self._request("GET", "/entries.json", params=params)

    def get_entry(self, entry_id: int) -> Dict[str, Any]:
        """Get a single entry by ID."""
        return self._request("GET", f"/entries/{entry_id}.json")

    def add_entry(self, url: str, title: str = None, tags: str = None,
                  archive: int = 0, starred: int = 0, content: str = None,
                  language: str = None, published_at: str = None,
                  authors: str = None, public: int = None,
                  origin_url: str = None) -> Dict[str, Any]:
        """
        Add a new entry to Wallabag.

        Args:
            url: URL of the article to save
            title: Optional custom title
            tags: Comma-separated tags
            archive: 1 to mark as read
            starred: 1 to mark as starred
            content: Optional custom content (HTML)
            language: Language code (e.g., en, fr)
            published_at: Publication date
            authors: Comma-separated authors
            public: 1 to make public
            origin_url: Original URL if different

        Returns:
            Created entry data
        """
        data = {"url": url}

        if title:
            data["title"] = title
        if tags:
            data["tags"] = tags
        if archive:
            data["archive"] = archive
        if starred:
            data["starred"] = starred
        if content:
            data["content"] = content
        if language:
            data["language"] = language
        if published_at:
            data["published_at"] = published_at
        if authors:
            data["authors"] = authors
        if public is not None:
            data["public"] = public
        if origin_url:
            data["origin_url"] = origin_url

        return self._request("POST", "/entries.json", json=data)

    def update_entry(self, entry_id: int, title: str = None, tags: str = None,
                     archive: int = None, starred: int = None, content: str = None,
                     language: str = None, published_at: str = None,
                     authors: str = None, public: int = None,
                     origin_url: str = None) -> Dict[str, Any]:
        """Update an existing entry."""
        data = {}

        if title is not None:
            data["title"] = title
        if tags is not None:
            data["tags"] = tags
        if archive is not None:
            data["archive"] = archive
        if starred is not None:
            data["starred"] = starred
        if content is not None:
            data["content"] = content
        if language is not None:
            data["language"] = language
        if published_at is not None:
            data["published_at"] = published_at
        if authors is not None:
            data["authors"] = authors
        if public is not None:
            data["public"] = public
        if origin_url is not None:
            data["origin_url"] = origin_url

        return self._request("PATCH", f"/entries/{entry_id}.json", json=data)

    def delete_entry(self, entry_id: int) -> Dict[str, Any]:
        """Delete an entry."""
        return self._request("DELETE", f"/entries/{entry_id}.json")

    def archive_entry(self, entry_id: int) -> Dict[str, Any]:
        """Mark an entry as archived (read)."""
        return self.update_entry(entry_id, archive=1)

    def star_entry(self, entry_id: int) -> Dict[str, Any]:
        """Mark an entry as starred."""
        return self.update_entry(entry_id, starred=1)

    def unstar_entry(self, entry_id: int) -> Dict[str, Any]:
        """Remove star from an entry."""
        return self.update_entry(entry_id, starred=0)

    def get_tags(self) -> List[Dict[str, Any]]:
        """Get all tags."""
        return self._request("GET", "/tags.json")

    def get_entry_tags(self, entry_id: int) -> List[Dict[str, Any]]:
        """Get tags for a specific entry."""
        return self._request("GET", f"/entries/{entry_id}/tags.json")

    def add_entry_tags(self, entry_id: int, tags: str) -> Dict[str, Any]:
        """Add tags to an entry."""
        return self._request("POST", f"/entries/{entry_id}/tags.json", json={"tags": tags})

    def delete_entry_tag(self, entry_id: int, tag_id: int) -> Dict[str, Any]:
        """Remove a tag from an entry."""
        return self._request("DELETE", f"/entries/{entry_id}/tags/{tag_id}.json")

    def get_version(self) -> str:
        """Get Wallabag server version."""
        result = self._request("GET", "/version.json")
        return result if isinstance(result, str) else result.get("version", "unknown")

    def exists(self, url: str) -> Dict[str, Any]:
        """Check if a URL already exists in Wallabag."""
        return self._request("GET", "/entries/exists.json", params={"url": url})

    def export_entry(self, entry_id: int, format: str = "epub") -> bytes:
        """
        Export an entry to a specific format.

        Args:
            entry_id: Entry ID
            format: Export format (epub, mobi, pdf, txt, csv, json, xml)

        Returns:
            Binary content of exported file
        """
        self._ensure_authenticated()

        url = f"{self.api_url}/entries/{entry_id}/export.{format}"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        return response.content


# Global client instance (per-user clients stored in cache)
_clients: Dict[int, WallabagClient] = {}


def get_client(user_id: int, host: str = None, client_id: str = None,
               client_secret: str = None, username: str = None,
               password: str = None, access_token: str = None,
               refresh_token: str = None) -> Optional[WallabagClient]:
    """
    Get or create a Wallabag client for a user.

    Args:
        user_id: Calibre-Web user ID
        host: Wallabag server URL
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        username: Wallabag username
        password: Wallabag password
        access_token: Existing access token
        refresh_token: Existing refresh token

    Returns:
        WallabagClient instance or None if not configured
    """
    global _clients

    if user_id in _clients:
        client = _clients[user_id]
        # Check if configuration changed
        if host and client.host != host.rstrip('/'):
            del _clients[user_id]
        else:
            return client

    if not all([host, client_id, client_secret]):
        return None

    client = WallabagClient(
        host=host,
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        access_token=access_token,
        refresh_token=refresh_token,
    )

    _clients[user_id] = client
    return client


def clear_client(user_id: int):
    """Remove cached client for a user."""
    global _clients
    if user_id in _clients:
        del _clients[user_id]


def get_cached_entries(user_id: int, client: WallabagClient,
                       force_refresh: bool = False, **kwargs) -> List[Dict[str, Any]]:
    """
    Get entries with caching.

    Args:
        user_id: User ID for cache key
        client: WallabagClient instance
        force_refresh: Force cache refresh
        **kwargs: Arguments passed to get_entries

    Returns:
        List of entries
    """
    global _ARTICLES_CACHE

    cache_key = f"{user_id}_{hash(frozenset(kwargs.items()))}"
    now = time.time()

    if not force_refresh and cache_key in _ARTICLES_CACHE:
        cached = _ARTICLES_CACHE[cache_key]
        if now < cached["timestamp"] + _CACHE_TIMEOUT:
            return cached["entries"]

    try:
        result = client.get_entries(**kwargs)
        entries = result.get("_embedded", {}).get("items", [])

        _ARTICLES_CACHE[cache_key] = {
            "timestamp": now,
            "entries": entries,
        }

        return entries

    except WallabagError as e:
        log.error(f"Failed to fetch Wallabag entries: {e}")
        # Return cached data if available, even if expired
        if cache_key in _ARTICLES_CACHE:
            return _ARTICLES_CACHE[cache_key]["entries"]
        return []


def clear_cache(user_id: int = None):
    """Clear entry cache for a user or all users."""
    global _ARTICLES_CACHE

    if user_id is None:
        _ARTICLES_CACHE = {}
    else:
        keys_to_delete = [k for k in _ARTICLES_CACHE if k.startswith(f"{user_id}_")]
        for key in keys_to_delete:
            del _ARTICLES_CACHE[key]
