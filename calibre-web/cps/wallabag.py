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
Wallabag Integration Blueprint

This module provides Flask routes for integrating Wallabag articles
into Calibre-Web. Users can view, manage, and read their saved articles
alongside their ebook collection.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_babel import gettext as _

from . import logger, config
from .cw_login import login_required, current_user
from .render_template import render_title_template
from .services import wallabag as wallabag_service
from .services.wallabag import WallabagClient, WallabagError, WallabagAuthError
from . import ub

log = logger.create()

wallabag_bp = Blueprint('wallabag', __name__)


def get_user_wallabag_config():
    """Get Wallabag configuration for current user."""
    if not current_user.is_authenticated:
        return None

    wb_config = ub.session.query(ub.WallabagConfig).filter(
        ub.WallabagConfig.user_id == current_user.id
    ).first()

    return wb_config


def get_wallabag_client():
    """Get Wallabag client for current user."""
    wb_config = get_user_wallabag_config()
    if not wb_config or not wb_config.enabled:
        return None

    return wallabag_service.get_client(
        user_id=current_user.id,
        host=wb_config.host,
        client_id=wb_config.client_id,
        client_secret=wb_config.client_secret,
        username=wb_config.username,
        password=wb_config.password,
        access_token=wb_config.access_token,
        refresh_token=wb_config.refresh_token,
    )


def save_tokens(wb_config, client):
    """Save updated tokens to database."""
    if client.access_token != wb_config.access_token or \
       client.refresh_token != wb_config.refresh_token:
        wb_config.access_token = client.access_token
        wb_config.refresh_token = client.refresh_token
        ub.session.commit()


@wallabag_bp.route('/wallabag')
@login_required
def index():
    """Show Wallabag articles list."""
    client = get_wallabag_client()

    if not client:
        flash(_("Wallabag is not configured. Please set it up in your profile settings."), category="warning")
        return redirect(url_for('web.profile'))

    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', 'unread')  # unread, archived, starred, all
    per_page = 30

    # Map filter to API parameters
    archive = 0 if filter_type == 'unread' else (1 if filter_type == 'archived' else 2)
    starred = 1 if filter_type == 'starred' else 0

    try:
        if filter_type == 'starred':
            entries = wallabag_service.get_cached_entries(
                current_user.id, client, archive=2, starred=1, page=page, per_page=per_page
            )
        else:
            entries = wallabag_service.get_cached_entries(
                current_user.id, client, archive=archive, page=page, per_page=per_page
            )

        # Save any updated tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

    except WallabagError as e:
        log.error(f"Wallabag error: {e}")
        flash(_("Error connecting to Wallabag: %(error)s", error=str(e)), category="error")
        entries = []

    return render_title_template(
        'wallabag/index.html',
        entries=entries,
        title=_("Articles"),
        page="wallabag",
        filter_type=filter_type,
        current_page=page,
    )


@wallabag_bp.route('/wallabag/article/<int:entry_id>')
@login_required
def view_article(entry_id):
    """View a single Wallabag article."""
    client = get_wallabag_client()

    if not client:
        flash(_("Wallabag is not configured."), category="error")
        return redirect(url_for('web.index'))

    try:
        entry = client.get_entry(entry_id)

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

    except WallabagError as e:
        log.error(f"Failed to fetch article {entry_id}: {e}")
        flash(_("Error loading article: %(error)s", error=str(e)), category="error")
        return redirect(url_for('wallabag.index'))

    return render_title_template(
        'wallabag/article.html',
        entry=entry,
        title=entry.get('title', 'Article'),
        page="wallabag",
    )


@wallabag_bp.route('/wallabag/article/<int:entry_id>/archive', methods=['POST'])
@login_required
def archive_article(entry_id):
    """Toggle archive status of an article."""
    client = get_wallabag_client()

    if not client:
        return {"error": "Wallabag not configured"}, 400

    try:
        entry = client.get_entry(entry_id)
        is_archived = entry.get('is_archived', 0)

        if is_archived:
            client.update_entry(entry_id, archive=0)
            message = _("Article marked as unread")
        else:
            client.archive_entry(entry_id)
            message = _("Article archived")

        # Clear cache to reflect changes
        wallabag_service.clear_cache(current_user.id)

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": True, "message": message}

        flash(message, category="success")

    except WallabagError as e:
        log.error(f"Failed to archive article {entry_id}: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"error": str(e)}, 500
        flash(_("Error: %(error)s", error=str(e)), category="error")

    return redirect(request.referrer or url_for('wallabag.index'))


@wallabag_bp.route('/wallabag/article/<int:entry_id>/star', methods=['POST'])
@login_required
def star_article(entry_id):
    """Toggle star status of an article."""
    client = get_wallabag_client()

    if not client:
        return {"error": "Wallabag not configured"}, 400

    try:
        entry = client.get_entry(entry_id)
        is_starred = entry.get('is_starred', 0)

        if is_starred:
            client.unstar_entry(entry_id)
            message = _("Star removed")
        else:
            client.star_entry(entry_id)
            message = _("Article starred")

        # Clear cache
        wallabag_service.clear_cache(current_user.id)

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": True, "message": message, "is_starred": not is_starred}

        flash(message, category="success")

    except WallabagError as e:
        log.error(f"Failed to star article {entry_id}: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"error": str(e)}, 500
        flash(_("Error: %(error)s", error=str(e)), category="error")

    return redirect(request.referrer or url_for('wallabag.index'))


@wallabag_bp.route('/wallabag/article/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_article(entry_id):
    """Delete an article from Wallabag."""
    client = get_wallabag_client()

    if not client:
        return {"error": "Wallabag not configured"}, 400

    try:
        client.delete_entry(entry_id)

        # Clear cache
        wallabag_service.clear_cache(current_user.id)

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

        message = _("Article deleted")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": True, "message": message}

        flash(message, category="success")

    except WallabagError as e:
        log.error(f"Failed to delete article {entry_id}: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"error": str(e)}, 500
        flash(_("Error: %(error)s", error=str(e)), category="error")

    return redirect(url_for('wallabag.index'))


@wallabag_bp.route('/wallabag/article/<int:entry_id>/export/<format>')
@login_required
def export_article(entry_id, format):
    """Export an article to ebook format."""
    if format not in ['epub', 'mobi', 'pdf', 'txt']:
        abort(400, "Invalid format")

    client = get_wallabag_client()

    if not client:
        flash(_("Wallabag is not configured."), category="error")
        return redirect(url_for('wallabag.index'))

    try:
        entry = client.get_entry(entry_id)
        content = client.export_entry(entry_id, format)

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

        filename = f"{entry.get('title', 'article')[:50]}.{format}"
        # Clean filename
        filename = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '-', '_')).strip()

        content_types = {
            'epub': 'application/epub+zip',
            'mobi': 'application/x-mobipocket-ebook',
            'pdf': 'application/pdf',
            'txt': 'text/plain',
        }

        return Response(
            content,
            mimetype=content_types.get(format, 'application/octet-stream'),
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )

    except WallabagError as e:
        log.error(f"Failed to export article {entry_id}: {e}")
        flash(_("Error exporting article: %(error)s", error=str(e)), category="error")
        return redirect(url_for('wallabag.view_article', entry_id=entry_id))


@wallabag_bp.route('/wallabag/add', methods=['GET', 'POST'])
@login_required
def add_article():
    """Add a new article to Wallabag."""
    client = get_wallabag_client()

    if not client:
        flash(_("Wallabag is not configured."), category="error")
        return redirect(url_for('web.profile'))

    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        tags = request.form.get('tags', '').strip()

        if not url:
            flash(_("URL is required"), category="error")
            return render_title_template('wallabag/add.html', title=_("Add Article"), page="wallabag")

        try:
            # Check if URL already exists
            exists_result = client.exists(url)
            if exists_result.get('exists'):
                flash(_("This URL is already saved in Wallabag"), category="warning")
                return redirect(url_for('wallabag.view_article', entry_id=exists_result.get('entry')))

            entry = client.add_entry(url=url, tags=tags if tags else None)

            # Clear cache
            wallabag_service.clear_cache(current_user.id)

            # Save tokens
            wb_config = get_user_wallabag_config()
            if wb_config:
                save_tokens(wb_config, client)

            flash(_("Article saved successfully"), category="success")
            return redirect(url_for('wallabag.view_article', entry_id=entry.get('id')))

        except WallabagError as e:
            log.error(f"Failed to add article: {e}")
            flash(_("Error saving article: %(error)s", error=str(e)), category="error")

    return render_title_template('wallabag/add.html', title=_("Add Article"), page="wallabag")


@wallabag_bp.route('/wallabag/tags')
@login_required
def tags():
    """Show all Wallabag tags."""
    client = get_wallabag_client()

    if not client:
        flash(_("Wallabag is not configured."), category="error")
        return redirect(url_for('web.profile'))

    try:
        tags_list = client.get_tags()

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

    except WallabagError as e:
        log.error(f"Failed to fetch tags: {e}")
        flash(_("Error loading tags: %(error)s", error=str(e)), category="error")
        tags_list = []

    return render_title_template(
        'wallabag/tags.html',
        tags=tags_list,
        title=_("Tags"),
        page="wallabag",
    )


@wallabag_bp.route('/wallabag/tag/<tag_slug>')
@login_required
def articles_by_tag(tag_slug):
    """Show articles with a specific tag."""
    client = get_wallabag_client()

    if not client:
        flash(_("Wallabag is not configured."), category="error")
        return redirect(url_for('web.profile'))

    page = request.args.get('page', 1, type=int)

    try:
        entries = wallabag_service.get_cached_entries(
            current_user.id, client, archive=2, tags=tag_slug, page=page, per_page=30
        )

        # Save tokens
        wb_config = get_user_wallabag_config()
        if wb_config:
            save_tokens(wb_config, client)

    except WallabagError as e:
        log.error(f"Failed to fetch articles by tag: {e}")
        flash(_("Error loading articles: %(error)s", error=str(e)), category="error")
        entries = []

    return render_title_template(
        'wallabag/index.html',
        entries=entries,
        title=_("Tag: %(tag)s", tag=tag_slug),
        page="wallabag",
        filter_type="tag",
        tag_slug=tag_slug,
        current_page=page,
    )


@wallabag_bp.route('/wallabag/refresh')
@login_required
def refresh():
    """Force refresh of Wallabag cache."""
    wallabag_service.clear_cache(current_user.id)
    flash(_("Article list refreshed"), category="success")
    return redirect(url_for('wallabag.index'))


@wallabag_bp.route('/wallabag/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Wallabag configuration settings."""
    wb_config = get_user_wallabag_config()

    if not wb_config:
        wb_config = ub.WallabagConfig(user_id=current_user.id)
        ub.session.add(wb_config)
        ub.session.commit()

    if request.method == 'POST':
        wb_config.enabled = 'enabled' in request.form
        wb_config.host = request.form.get('host', '').strip().rstrip('/')
        wb_config.client_id = request.form.get('client_id', '').strip()
        wb_config.client_secret = request.form.get('client_secret', '').strip()
        wb_config.username = request.form.get('username', '').strip()

        # Only update password if provided
        new_password = request.form.get('password', '').strip()
        if new_password:
            wb_config.password = new_password

        # Clear tokens to force re-authentication
        wb_config.access_token = None
        wb_config.refresh_token = None

        # Clear cached client
        wallabag_service.clear_client(current_user.id)
        wallabag_service.clear_cache(current_user.id)

        ub.session.commit()

        # Test connection if enabled
        if wb_config.enabled and wb_config.host and wb_config.client_id:
            try:
                client = get_wallabag_client()
                if client:
                    client.authenticate()
                    # Save new tokens
                    wb_config.access_token = client.access_token
                    wb_config.refresh_token = client.refresh_token
                    ub.session.commit()
                    flash(_("Wallabag connected successfully!"), category="success")
            except WallabagAuthError as e:
                flash(_("Authentication failed: %(error)s", error=str(e)), category="error")
            except WallabagError as e:
                flash(_("Connection failed: %(error)s", error=str(e)), category="error")
        else:
            flash(_("Settings saved"), category="success")

        return redirect(url_for('wallabag.settings'))

    return render_title_template(
        'wallabag/settings.html',
        wb_config=wb_config,
        title=_("Wallabag Settings"),
        page="wallabag_settings",
    )


@wallabag_bp.route('/wallabag/test')
@login_required
def test_connection():
    """Test Wallabag connection."""
    client = get_wallabag_client()

    if not client:
        return {"success": False, "error": "Wallabag not configured"}

    try:
        version = client.get_version()
        return {"success": True, "version": version}
    except WallabagError as e:
        return {"success": False, "error": str(e)}
