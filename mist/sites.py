import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import ui
from session import api_request, _paginate, DEFAULT_TIMEOUT

_SITE_SETTINGS_STRIP_FIELDS = {
    "id", "org_id", "site_id", "for_site", "created_time", "modified_time",
    "networktemplate_id", "gatewaytemplate_id", "rftemplate_id", "alarmtemplate_id"
}

_SITE_WLAN_STRIP_FIELDS = {"id", "org_id", "site_id", "created_time", "modified_time"}

_SITE_MAP_STRIP_FIELDS = {"id", "org_id", "site_id", "created_time", "modified_time", "url", "thumbnail_url"}


def get_site_details(session, site_id, base_url):
    url = f"{base_url}/sites/{site_id}"
    response = api_request(session, "GET", url)
    return response.json()


def create_site(session, org_id, site_name, site_address, country_code, base_url, timezone=None):
    url = f'{base_url}/orgs/{org_id}/sites'
    payload = {'name': site_name, 'address': site_address, 'country_code': country_code}
    if timezone:
        payload['timezone'] = timezone
    response = api_request(session, "POST", url, payload=payload)
    return response.json()['id']


def get_site_settings(session, site_id, base_url):
    url = f'{base_url}/sites/{site_id}/setting'
    response = api_request(session, "GET", url)
    return response.json()


def copy_site_settings(session, source_site_id, target_site_id,
                       source_base_url, dest_base_url, dest_session=None,
                       _cached_settings=None):
    _dst_sess = dest_session or session
    site_settings = _cached_settings if _cached_settings is not None \
        else get_site_settings(session, source_site_id, base_url=source_base_url)
    cleaned = {k: v for k, v in site_settings.items() if k not in _SITE_SETTINGS_STRIP_FIELDS}
    url = f'{dest_base_url}/sites/{target_site_id}/setting'
    api_request(_dst_sess, "PUT", url, payload=cleaned)


def fetch_site_wlans(session, site_id, base_url):
    url = f'{base_url}/sites/{site_id}/wlans'
    try:
        return _paginate(session, url)
    except Exception as exc:
        ui.warn(f"Could not fetch site WLANs for site {site_id}: {exc}")
        return []


def clone_site_wlans(source_session, dest_session, source_site_id, dest_site_id,
                     source_base_url, dest_base_url, _cached_wlans=None):
    _dst_sess = dest_session or source_session
    wlans = _cached_wlans if _cached_wlans is not None \
        else fetch_site_wlans(source_session, source_site_id, base_url=source_base_url)
    if not wlans:
        return 0
    create_url = f'{dest_base_url}/sites/{dest_site_id}/wlans'
    ok = 0
    for wlan in wlans:
        payload = {k: v for k, v in wlan.items() if k not in _SITE_WLAN_STRIP_FIELDS}
        try:
            api_request(_dst_sess, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok += 1
        except Exception as exc:
            ui.warn(f"Site WLAN '{wlan.get('ssid', wlan.get('id'))}' skipped: {exc}")
    return ok


def fetch_site_maps(session, site_id, base_url):
    url = f'{base_url}/sites/{site_id}/maps'
    try:
        return _paginate(session, url)
    except Exception as exc:
        ui.warn(f"Could not fetch site maps for site {site_id}: {exc}")
        return []


def clone_site_maps(source_session, dest_session, source_site_id, dest_site_id,
                    source_base_url, dest_base_url, _cached_maps=None):
    _dst_sess = dest_session or source_session

    maps = _cached_maps if _cached_maps is not None \
        else fetch_site_maps(source_session, source_site_id, base_url=source_base_url)
    if not maps:
        return 0

    create_url = f'{dest_base_url}/sites/{dest_site_id}/maps'

    def _upload_image(map_name, new_map_id, source_image_url):
        try:
            img_resp = requests.get(source_image_url, timeout=DEFAULT_TIMEOUT)
            if img_resp.status_code != 200:
                ui.warn(f"Could not download map image for '{map_name}': HTTP {img_resp.status_code}")
                return
            content_type = img_resp.headers.get("Content-Type", "application/octet-stream")
            filename = source_image_url.split("/")[-1].split("?")[0] or "map_image"
            upload_url = f'{dest_base_url}/sites/{dest_site_id}/maps/{new_map_id}/image'
            up_resp = _dst_sess.post(
                upload_url,
                files={'file': (filename, img_resp.content, content_type)},
                headers={'Content-Type': None},
                timeout=DEFAULT_TIMEOUT,
            )
            if up_resp.status_code not in (200, 201):
                ui.warn(f"Map image upload failed for '{map_name}': {up_resp.text[:200]}")
        except Exception as exc:
            ui.warn(f"Map image upload skipped for '{map_name}': {exc}")

    image_tasks = []
    ok = 0
    for site_map in maps:
        source_image_url = site_map.get("url")
        payload = {k: v for k, v in site_map.items() if k not in _SITE_MAP_STRIP_FIELDS}
        try:
            resp = api_request(_dst_sess, "POST", create_url, payload=payload, ok_status=(200, 201))
            new_map_id = resp.json().get("id")
        except Exception as exc:
            ui.warn(f"Site map '{site_map.get('name', site_map.get('id'))}' skipped: {exc}")
            continue

        if source_image_url and new_map_id:
            image_tasks.append((site_map.get("name", new_map_id), new_map_id, source_image_url))
        ok += 1

    if image_tasks:
        with ThreadPoolExecutor(max_workers=min(len(image_tasks), 8)) as ex:
            list(ex.map(lambda t: _upload_image(*t), image_tasks))

    return ok


def _prefetch_source_site_data(source_session, site_id, source_base_url):
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(get_site_settings, source_session, site_id, source_base_url): "settings",
            pool.submit(fetch_site_wlans,  source_session, site_id, source_base_url): "wlans",
            pool.submit(fetch_site_maps,   source_session, site_id, source_base_url): "maps",
            pool.submit(get_site_details,  source_session, site_id, source_base_url): "details",
        }
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:
                results[key] = None
                ui.warn(f"Pre-fetch '{key}' failed for source site {site_id}: {exc}")
    return results
