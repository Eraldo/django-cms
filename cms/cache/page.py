# -*- coding: utf-8 -*-

import hashlib

from datetime import timedelta

from django.conf import settings
from django.utils.cache import add_never_cache_headers, patch_response_headers
from django.utils.encoding import iri_to_uri, force_text
from django.utils.timezone import now, get_current_timezone_name

from cms.cache import _get_cache_version, _set_cache_version, _get_cache_key
from cms.constants import EXPIRE_NOW, MAX_EXPIRATION_TTL
from cms.utils import get_cms_setting


def _page_cache_key(request):
    #md5 key of current path
    cache_key = "%s:%d:%s" % (
        get_cms_setting("CACHE_PREFIX"),
        settings.SITE_ID,
        hashlib.md5(iri_to_uri(request.get_full_path()).encode('utf-8')).hexdigest()
    )
    if settings.USE_TZ:
        # The datetime module doesn't restrict the output of tzname().
        # Windows is known to use non-standard, locale-dependant names.
        # User-defined tzinfo classes may return absolutely anything.
        # Hence this paranoid conversion to create a valid cache key.
        tz_name = force_text(get_current_timezone_name(), errors='ignore')
        cache_key += '.%s' % tz_name.encode('ascii', 'ignore').decode('ascii').replace(' ', '_')
    return cache_key


def set_page_cache(response):
    from django.core.cache import cache

    request = response._request

    if get_cms_setting("PAGE_CACHE") and (
            not hasattr(request, 'toolbar') or (
                not request.toolbar.edit_mode and
                not request.toolbar.show_toolbar and
                not request.user.is_authenticated()
            )):

        # This *must* be TZ-aware
        timestamp = now()

        placeholders = [ph for ph, __ in getattr(request, 'placeholders', {}).values()]

        # Checks if there's a plugin using the legacy "cache = False"
        if all(ph.cache_placeholder for ph in placeholders):
            placeholder_ttl_list = [
                # get_cache_expiration() always returns:
                #     EXPIRE_NOW <= int <= MAX_EXPIRATION_IN_SECONDS
                ph.get_cache_expiration(request, timestamp)
                for ph in placeholders
            ]

            if EXPIRE_NOW not in placeholder_ttl_list:
                if placeholder_ttl_list:
                    min_placeholder_ttl = min(x for x in placeholder_ttl_list)
                else:
                    # Should only happen when there are no placeholders at all
                    min_placeholder_ttl = MAX_EXPIRATION_TTL
                ttl = min(
                    get_cms_setting('CACHE_DURATIONS')['content'],
                    min_placeholder_ttl
                )

                if ttl > 0:
                    # Adds expiration, etc. to headers
                    patch_response_headers(response, cache_timeout=ttl)
                    version = _get_cache_version()
                    # We also store the absolute expiration timestamp to avoid
                    # recomputing it on cache-reads.
                    expires_datetime = timestamp + timedelta(seconds=ttl)
                    cache.set(
                        _page_cache_key(request),
                        (
                            response.content,
                            response._headers,
                            expires_datetime,
                        ),
                        ttl,
                        version=version
                    )
                    # See note in invalidate_cms_page_cache()
                    _set_cache_version(version)
                    return response

    add_never_cache_headers(response)
    return response


def get_page_cache(request):
    from django.core.cache import cache
    return cache.get(_page_cache_key(request), version=_get_cache_version())


def get_xframe_cache(page):
    from django.core.cache import cache
    return cache.get('cms:xframe_options:%s' % page.pk)


def set_xframe_cache(page, xframe_options):
    from django.core.cache import cache
    cache.set('cms:xframe_options:%s' % page.pk,
              xframe_options,
              version=_get_cache_version())
    _set_cache_version(_get_cache_version())


def _page_url_key(page_lookup, lang, site_id):
    return _get_cache_key('page_url', page_lookup, lang, site_id) + '_type:absolute_url'


def set_page_url_cache(page_lookup, lang, site_id, url):
    from django.core.cache import cache
    cache.set(_page_url_key(page_lookup, lang, site_id),
              url,
              get_cms_setting('CACHE_DURATIONS')['content'], version=_get_cache_version())
    _set_cache_version(_get_cache_version())


def get_page_url_cache(page_lookup, lang, site_id):
    from django.core.cache import cache
    return cache.get(_page_url_key(page_lookup, lang, site_id),
                     version=_get_cache_version())
