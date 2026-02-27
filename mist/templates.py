from concurrent.futures import ThreadPoolExecutor, as_completed

import ui
from session import api_request, _paginate
from prompts import prompt_input, select_name_from_list


def fetch_templates(session, org_id, base_url):
    endpoints = {
        "switch":   f"{base_url}/orgs/{org_id}/networktemplates",
        "wan_edge": f"{base_url}/orgs/{org_id}/gatewaytemplates",
        "wlan":     f"{base_url}/orgs/{org_id}/templates",
        "rf":       f"{base_url}/orgs/{org_id}/rftemplates",
    }
    templates = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_paginate, session, url): key for key, url in endpoints.items()}
        for future in as_completed(futures):
            templates[futures[future]] = future.result()
    return templates


def build_template_maps(session, source_org_id, new_org_id,
                        source_base_url, dest_base_url, dest_session=None):
    _dst_sess = dest_session or session
    source_templates = fetch_templates(session,   source_org_id, base_url=source_base_url)
    new_templates    = fetch_templates(_dst_sess, new_org_id,    base_url=dest_base_url)

    source_id_to_name = {}
    for key, items in source_templates.items():
        source_id_to_name[key] = {item.get("id"): item.get("name") for item in items}

    new_name_to_id = {}
    for key, items in new_templates.items():
        new_name_to_id[key] = {item.get("name"): item.get("id") for item in items}

    return source_id_to_name, new_name_to_id, new_templates


def build_wlan_scope_info(session, org_id, base_url):
    url = f'{base_url}/orgs/{org_id}/templates'
    site_map: dict = {}
    org_level_ids: set = set()

    def _add_site(sid, tid):
        if sid and tid:
            site_map.setdefault(sid, [])
            if tid not in site_map[sid]:
                site_map[sid].append(tid)

    for template in _paginate(session, url):
        template_id = template.get("id")
        if not template_id:
            continue
        applies = template.get("applies")
        if isinstance(applies, dict):
            if applies.get("org_id"):
                org_level_ids.add(template_id)
                continue
            _add_site(applies.get("site_id"), template_id)
            for sid in (applies.get("site_ids") or []):
                _add_site(sid, template_id)
        elif isinstance(applies, list):
            for entry in applies:
                if isinstance(entry, dict):
                    _add_site(entry.get("site_id"), template_id)
        else:
            _add_site(template.get("site_id"), template_id)

    return site_map, org_level_ids


def build_wlan_site_template_map(session, org_id, base_url):
    site_map, _ = build_wlan_scope_info(session, org_id, base_url=base_url)
    return site_map


def build_new_template_id_map(new_templates):
    id_map = {
        "switch_template_id": {},
        "wan_edge_template_id": {},
        "wlan_template_id": {},
        "rftemplate_id": {}
    }
    mapping = {
        "switch": "switch_template_id",
        "wan_edge": "wan_edge_template_id",
        "wlan": "wlan_template_id",
        "rf": "rftemplate_id"
    }
    for key, items in new_templates.items():
        target_key = mapping.get(key)
        if not target_key:
            continue
        for item in items:
            template_id = item.get("id")
            name = item.get("name")
            if template_id and name:
                id_map[target_key][template_id] = name
    return id_map


def format_assigned_template_names(template_ids, id_name_map):
    _name_key = {
        "switch_template_id":   "switch_template_id",
        "wan_edge_template_id": "wan_edge_template_id",
        "wlan_template_id":     "wlan_template_id",
        "wlan_org_template_id": "wlan_template_id",
        "rftemplate_id":        "rftemplate_id",
    }
    labels = {
        "switch_template_id":   "switch",
        "wan_edge_template_id": "wan edge",
        "wlan_template_id":     "wlan (site)",
        "wlan_org_template_id": "wlan (org)",
        "rftemplate_id":        "rf",
    }
    parts = []
    for key, label in labels.items():
        template_id = template_ids.get(key)
        if not template_id:
            if key == "wlan_org_template_id":
                continue
            parts.append(f"{label}=<none>")
            continue
        nk = _name_key[key]
        if isinstance(template_id, list):
            names = [id_name_map.get(nk, {}).get(item, item) for item in template_id]
            parts.append(f"{label}={'|'.join(names)}")
        else:
            name = id_name_map.get(nk, {}).get(template_id, template_id)
            parts.append(f"{label}={name}")
    return ", ".join(parts)


def format_template_skip_warnings(skip_reasons):
    labels = {
        "switch_template_id":   "switch",
        "wan_edge_template_id": "wan edge",
        "wlan_template_id":     "wlan (site)",
        "wlan_org_template_id": "wlan (org)",
        "rftemplate_id":        "rf",
    }
    parts = []
    for key in labels:
        reason = skip_reasons.get(key)
        if reason:
            parts.append(f"{labels[key]}=skipped ({reason})")
    return ", ".join(parts)


def compute_mode4_skip_reasons(source_template_ids, resolved_template_ids, source_maps):
    skip_reasons = {}
    source_to_assignment_keys = {
        "switch":   "switch_template_id",
        "wan_edge": "wan_edge_template_id",
        "wlan":     "wlan_template_id",
        "wlan_org": "wlan_org_template_id",
        "rf":       "rftemplate_id",
    }
    for source_key, assignment_key in source_to_assignment_keys.items():
        source_id = source_template_ids.get(source_key)
        if not source_id:
            continue
        if resolved_template_ids.get(source_key):
            continue
        map_key = "wlan" if source_key == "wlan_org" else source_key
        if isinstance(source_id, list):
            missing_names = [
                source_maps.get(map_key, {}).get(item, item) for item in source_id
            ]
            skip_reasons[assignment_key] = f"unmatched templates: {', '.join(missing_names)}"
        else:
            source_name = source_maps.get(map_key, {}).get(source_id)
            if source_name:
                skip_reasons[assignment_key] = f"source template '{source_name}' not found in target org"
            else:
                skip_reasons[assignment_key] = f"source template id '{source_id}' could not be resolved by name"
    return skip_reasons


def derive_source_site_template_ids(site_details, site_id=None,
                                    wlan_site_map=None, wlan_org_level_ids=None):
    template_ids = {
        "switch":   site_details.get("networktemplate_id"),
        "wan_edge": site_details.get("gatewaytemplate_id"),
        "rf":       site_details.get("rftemplate_id"),
        "wlan":     [],
        "wlan_org": [],
    }

    for key in ["wlan_template_id", "template_id", "wlan_template"]:
        if site_details.get(key):
            template_ids["wlan"].append(site_details[key])
            break

    if isinstance(site_details.get("wlan_template_ids"), list) and site_details["wlan_template_ids"]:
        template_ids["wlan"].extend(site_details["wlan_template_ids"])

    if wlan_site_map and site_id:
        template_ids["wlan"].extend(wlan_site_map.get(site_id, []))

    if wlan_org_level_ids:
        template_ids["wlan_org"].extend(wlan_org_level_ids)

    template_ids["wlan"]     = template_ids["wlan"]     or None
    template_ids["wlan_org"] = template_ids["wlan_org"] or None

    return template_ids


def resolve_template_ids_from_source(site_details, source_maps, new_maps,
                                     site_id=None, wlan_site_map=None,
                                     wlan_org_level_ids=None):
    source_ids = derive_source_site_template_ids(
        site_details,
        site_id=site_id,
        wlan_site_map=wlan_site_map,
        wlan_org_level_ids=wlan_org_level_ids,
    )
    resolved = {}

    for key, source_id in source_ids.items():
        if not source_id:
            continue

        if key in {"wlan", "wlan_org"} and isinstance(source_id, list):
            resolved_list = []
            for wlan_id in source_id:
                source_name = source_maps.get("wlan", {}).get(wlan_id)
                if not source_name:
                    continue
                new_id = new_maps.get("wlan", {}).get(source_name)
                if new_id:
                    resolved_list.append(new_id)
            if resolved_list:
                resolved[key] = resolved_list
            continue

        source_name = source_maps.get(key, {}).get(source_id)
        if not source_name:
            continue
        new_id = new_maps.get(key, {}).get(source_name)
        if new_id:
            resolved[key] = new_id

    return resolved


def normalize_template_ids(template_ids):
    normalized = {
        "switch_template_id":   template_ids.get("switch"),
        "wan_edge_template_id": template_ids.get("wan_edge"),
        "wlan_template_id":     template_ids.get("wlan"),
        "wlan_org_template_id": template_ids.get("wlan_org"),
        "rftemplate_id":        template_ids.get("rf"),
    }
    return {k: v for k, v in normalized.items() if v}


def prompt_template_assignment_mode():
    ui.menu("Template Assignment Mode", [
        ("1", "Clone all templates — select assignments per site"),
        ("2", "Clone all templates — select one template per type for all sites"),
        ("3", "Clone a single template per type (select once), assign to all sites"),
        ("4", "Match each site to its current templates"),
    ])
    return prompt_input("Select option", default="2")


def prompt_template_choices_for_org(templates, label_prefix=""):
    choices = {}
    label_map = {
        "switch": "switch templates",
        "wan_edge": "wan edge templates",
        "wlan": "wlan templates",
        "rf": "rf templates"
    }
    for key, items in templates.items():
        label = label_map[key]
        if label_prefix:
            label = f"{label_prefix} {label}"
        choice = select_name_from_list(items, label)
        if choice:
            choices[key] = choice
    return choices


def assign_templates(session, org_id, site_id, template_ids, base_url):
    non_wlan = {
        "switch_template_id":   {"networktemplate_id": template_ids.get("switch_template_id")},
        "wan_edge_template_id": {"gatewaytemplate_id": template_ids.get("wan_edge_template_id")},
        "rftemplate_id":        {"rftemplate_id":       template_ids.get("rftemplate_id")},
    }
    for key, payload in non_wlan.items():
        if not template_ids.get(key):
            continue
        url = f'{base_url}/sites/{site_id}'
        api_request(session, "PUT", url, payload=payload)
        ui.ok(f"{key.replace('_', ' ').title()} assigned.")


def finalize_wlan_assignments(session, new_org_id, site_level_map, org_level_ids,
                              id_name_map, base_url):
    if not site_level_map and not org_level_ids:
        return

    ui.section("WLAN Template Assignment")

    for wlan_id, new_site_ids in site_level_map.items():
        name = id_name_map.get("wlan_template_id", {}).get(wlan_id, wlan_id)
        url = f'{base_url}/orgs/{new_org_id}/templates/{wlan_id}'
        payload = {"applies": {"site_ids": new_site_ids}}
        api_request(session, "PUT", url, payload=payload)
        ui.ok(f"WLAN (site-level) '{name}'  →  {len(new_site_ids)} site(s): {new_site_ids}")

    for wlan_id in org_level_ids:
        name = id_name_map.get("wlan_template_id", {}).get(wlan_id, wlan_id)
        url = f'{base_url}/orgs/{new_org_id}/templates/{wlan_id}'
        payload = {"applies": {"org_id": new_org_id}}
        api_request(session, "PUT", url, payload=payload)
        ui.ok(f"WLAN (org-level)  '{name}'  →  applies to all sites in new org.")
