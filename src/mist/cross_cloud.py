from concurrent.futures import ThreadPoolExecutor, as_completed

import ui
from session import api_request, _paginate
from mist import _ORG_RESOURCE_STRIP_FIELDS
from mist.sitegroups import fetch_sitegroups
from mist.orgs import fetch_alarm_templates, clone_alarm_templates

_SERVICEPOLICY_STRIP_FIELDS = {"id", "org_id", "created_time", "modified_time"}
_ORG_WLAN_STRIP_FIELDS = {"id", "org_id", "site_id", "created_time", "modified_time", "portal_template_url"}


def remap_gateway_template_service_policies(session, source_org_id, new_org_id,
                                            source_base_url, dest_base_url,
                                            dest_session=None):
    _dst_sess = dest_session or session

    source_policies = _paginate(session, f'{source_base_url}/orgs/{source_org_id}/servicepolicies')

    source_id_to_name = {}
    source_name_to_action = {}
    for policy in source_policies:
        pid  = policy.get("id")
        name = policy.get("name")
        if pid and name:
            source_id_to_name[pid] = name
            source_name_to_action[name] = policy.get("action", "allow")

    new_policies = _paginate(_dst_sess, f'{dest_base_url}/orgs/{new_org_id}/servicepolicies')
    new_name_to_id = {}
    new_id_to_action = {}
    for policy in new_policies:
        pid  = policy.get("id")
        name = policy.get("name")
        if pid and name:
            new_name_to_id[name] = pid
            new_id_to_action[pid] = policy.get("action", "allow")

    create_url = f'{dest_base_url}/orgs/{new_org_id}/servicepolicies'
    created = 0
    for policy in source_policies:
        name = policy.get("name")
        if not name or name in new_name_to_id:
            continue
        payload = {k: v for k, v in policy.items() if k not in _SERVICEPOLICY_STRIP_FIELDS}
        try:
            response = api_request(_dst_sess, "POST", create_url, payload=payload, ok_status=(200, 201))
            new_id = response.json().get("id")
            if new_id:
                new_name_to_id[name] = new_id
                new_id_to_action[new_id] = policy.get("action", "allow")
                created += 1
        except Exception as exc:
            ui.warn(f"Service policy '{name}' could not be created: {exc}")

    if created:
        ui.ok(f"Service policies created in new org (missing from clone): {created}")

    source_id_to_new_id = {
        src_id: new_name_to_id[name]
        for src_id, name in source_id_to_name.items()
        if name in new_name_to_id
    }
    if source_policies:
        ui.ok(f"Service policy ID map built: {len(source_id_to_new_id)}/{len(source_id_to_name)} resolved.")

    source_gateway_templates = _paginate(session, f'{source_base_url}/orgs/{source_org_id}/gatewaytemplates')
    source_gw_by_name = {t.get("name"): t for t in source_gateway_templates if t.get("name")}

    gateway_templates = _paginate(_dst_sess, f'{dest_base_url}/orgs/{new_org_id}/gatewaytemplates')

    def _policy_sort_key(e):
        if e.get("servicepolicy_id"):
            action = new_id_to_action.get(e["servicepolicy_id"], "allow")
        else:
            action = e.get("action", "allow")
        return 0 if action in ("deny", "block") else 1

    for gw in gateway_templates:
        gw_id = gw.get("id")
        gw_name = gw.get("name", gw_id)

        source_gw = source_gw_by_name.get(gw_name)
        if not source_gw:
            ui.warn(f"Gateway template '{gw_name}' not found in source org — skipping policy rebuild.")
            continue

        source_svc_policies = source_gw.get("service_policies") or []
        if not source_svc_policies:
            continue

        new_svc_policies = []
        skipped = []
        for entry in source_svc_policies:
            src_id = entry.get("servicepolicy_id")

            if src_id:
                resolved_id = source_id_to_new_id.get(src_id)
                if resolved_id:
                    new_svc_policies.append({
                        "servicepolicy_id": resolved_id,
                        "path_preference": entry.get("path_preference", "WAN1")
                    })
                else:
                    skipped.append(src_id)
            else:
                new_svc_policies.append(entry)

        new_svc_policies.sort(key=_policy_sort_key)

        gw_url = f'{dest_base_url}/orgs/{new_org_id}/gatewaytemplates/{gw_id}'
        api_request(_dst_sess, "PUT", gw_url, payload={"service_policies": new_svc_policies})

        inline_count = sum(1 for e in new_svc_policies if not e.get("servicepolicy_id"))
        ref_count = len(new_svc_policies) - inline_count
        parts = []
        if ref_count:
            parts.append(f"{ref_count} referenced")
        if inline_count:
            parts.append(f"{inline_count} inline")
        ui.ok(f"Service policies → gateway template '{gw_name}': {', '.join(parts)} applied.")
        if skipped:
            ui.warn(f"{len(skipped)} unmatched referenced policy ID(s) skipped in '{gw_name}'.")


def cross_cloud_bootstrap_org(source_session, dest_session, source_org_id,
                               new_org_name, source_base_url, dest_base_url):
    ui.progress("Creating blank organization on destination cloud …")
    org_url = f"{dest_base_url}/orgs"
    response = api_request(dest_session, "POST", org_url,
                           payload={"name": new_org_name}, ok_status=(200, 201))
    new_org_id = response.json()["id"]
    ui.ok(f"Blank organization created  →  ID: {new_org_id}")

    ui.progress("Copying site groups …")
    source_sgs = fetch_sitegroups(source_session, source_org_id, base_url=source_base_url)
    sg_url = f"{dest_base_url}/orgs/{new_org_id}/sitegroups"
    sg_id_map: dict = {}
    sg_ok = 0
    for sg in source_sgs:
        old_id = sg.get("id")
        payload = {k: v for k, v in sg.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            resp = api_request(dest_session, "POST", sg_url, payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                sg_id_map[old_id] = new_id
            sg_ok += 1
        except Exception as exc:
            ui.warn(f"Sitegroup '{sg.get('name')}' skipped: {exc}")
    ui.ok(f"Site groups copied: {sg_ok}/{len(source_sgs)}")

    ui.progress("Copying services …")
    source_services = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/services")
    svc_id_map: dict = {}
    svc_create_url = f"{dest_base_url}/orgs/{new_org_id}/services"
    svc_ok = 0
    for service in source_services:
        old_id = service.get("id")
        payload = {k: v for k, v in service.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            resp = api_request(dest_session, "POST", svc_create_url,
                               payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                svc_id_map[old_id] = new_id
            svc_ok += 1
        except Exception as exc:
            ui.warn(f"Service '{service.get('name')}' skipped: {exc}")
    ui.ok(f"Services copied: {svc_ok}/{len(source_services)}")

    ui.progress("Copying service policies …")
    source_policies = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/servicepolicies")
    sp_id_map: dict = {}
    sp_create_url = f"{dest_base_url}/orgs/{new_org_id}/servicepolicies"
    sp_ok = 0
    for policy in source_policies:
        old_id = policy.get("id")
        payload = {k: v for k, v in policy.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            resp = api_request(dest_session, "POST", sp_create_url,
                               payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                sp_id_map[old_id] = new_id
            sp_ok += 1
        except Exception as exc:
            ui.warn(f"Service policy '{policy.get('name')}' skipped: {exc}")
    ui.ok(f"Service policies copied: {sp_ok}/{len(source_policies)}")

    ui.progress("Copying networks …")
    source_networks = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/networks")
    net_id_map: dict = {}
    net_create_url = f"{dest_base_url}/orgs/{new_org_id}/networks"
    net_ok = 0
    for network in source_networks:
        old_id = network.get("id")
        payload = {k: v for k, v in network.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            resp = api_request(dest_session, "POST", net_create_url,
                               payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                net_id_map[old_id] = new_id
            net_ok += 1
        except Exception as exc:
            ui.warn(f"Network '{network.get('name')}' skipped: {exc}")
    ui.ok(f"Networks copied: {net_ok}/{len(source_networks)}")

    parallel_tasks = [
        ("Switch",  "networktemplates"),
        ("RF",      "rftemplates"),
        ("WLAN",    "templates"),
    ]

    def _copy_template_type(label, endpoint):
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/{endpoint}")
        create_url = f"{dest_base_url}/orgs/{new_org_id}/{endpoint}"
        t_ok = 0
        id_map = {}
        for item in items:
            old_id = item.get("id")
            payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
            if endpoint == "templates":
                applies = payload.get("applies")
                if isinstance(applies, dict) and "org_id" in applies:
                    applies["org_id"] = new_org_id
                exceptions = payload.get("exceptions")
                if isinstance(exceptions, dict):
                    old_sg_ids = exceptions.get("sitegroup_ids") or []
                    if old_sg_ids:
                        exceptions["sitegroup_ids"] = [sg_id_map.get(sid, sid) for sid in old_sg_ids]
            try:
                resp = api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
                new_id = resp.json().get("id")
                if old_id and new_id:
                    id_map[old_id] = new_id
                t_ok += 1
            except Exception as exc:
                ui.warn(f"{label} template '{item.get('name')}' skipped: {exc}")
        return label, t_ok, len(items), id_map

    wlan_template_id_map = {}
    ui.progress("Copying Switch, RF and WLAN templates in parallel …")
    with ThreadPoolExecutor(max_workers=3) as _ex:
        _template_futures = {_ex.submit(_copy_template_type, lbl, ep): lbl
                             for lbl, ep in parallel_tasks}
        for _future in as_completed(_template_futures):
            _lbl, _t_ok, _total, _id_map = _future.result()
            ui.ok(f"{_lbl} templates copied: {_t_ok}/{_total}")
            if _lbl == "WLAN":
                wlan_template_id_map = _id_map

    ui.progress("Copying org-level WLANs …")
    source_org_wlans = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/wlans")
    wlan_create_url = f"{dest_base_url}/orgs/{new_org_id}/wlans"
    wlan_ok = 0
    for wlan in source_org_wlans:
        payload = {k: v for k, v in wlan.items() if k not in _ORG_WLAN_STRIP_FIELDS}
        old_tmpl_id = payload.get("template_id")
        if old_tmpl_id and old_tmpl_id in wlan_template_id_map:
            payload["template_id"] = wlan_template_id_map[old_tmpl_id]
        try:
            api_request(dest_session, "POST", wlan_create_url, payload=payload, ok_status=(200, 201))
            wlan_ok += 1
        except Exception as exc:
            ui.warn(f"Org WLAN '{wlan.get('ssid', wlan.get('name'))}' skipped: {exc}")
    ui.ok(f"Org-level WLANs copied: {wlan_ok}/{len(source_org_wlans)}")

    ui.progress("Copying WAN Edge templates …")
    gw_items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/gatewaytemplates")
    gw_create_url = f"{dest_base_url}/orgs/{new_org_id}/gatewaytemplates"
    gw_ok = 0
    for item in gw_items:
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        old_svc = payload.get("service_policies") or []
        remapped = []
        for entry in old_svc:
            src_sp_id = entry.get("servicepolicy_id")
            if src_sp_id:
                remapped.append({**entry, "servicepolicy_id": sp_id_map.get(src_sp_id, src_sp_id)})
            else:
                remapped.append(entry)
        payload["service_policies"] = remapped
        if net_id_map:
            old_nets = payload.get("networks")
            if isinstance(old_nets, dict):
                payload["networks"] = {net_id_map.get(k, k): v for k, v in old_nets.items()}
        try:
            api_request(dest_session, "POST", gw_create_url, payload=payload, ok_status=(200, 201))
            gw_ok += 1
        except Exception as exc:
            ui.warn(f"WAN Edge template '{item.get('name')}' skipped: {exc}")
    ui.ok(f"WAN Edge templates copied: {gw_ok}/{len(gw_items)}")

    clone_alarm_templates(
        source_session, dest_session, source_org_id, new_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    return new_org_id


def preview_org_sync(source_session, dest_session, source_org_id, dest_org_id,
                     source_base_url, dest_base_url):
    """Parallel-fetch source and dest, report what's missing by name."""
    resource_types = [
        ("Site groups",        "sitegroups",       "name"),
        ("Services",           "services",         "name"),
        ("Service policies",   "servicepolicies",  "name"),
        ("Networks",           "networks",         "name"),
        ("Switch templates",   "networktemplates", "name"),
        ("RF templates",       "rftemplates",      "name"),
        ("WLAN templates",     "templates",        "name"),
        ("Org WLANs",          "wlans",            "ssid"),
        ("WAN Edge templates", "gatewaytemplates", "name"),
        ("Alarm templates",    "alarmtemplates",   "name"),
    ]

    all_data: dict = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {}
        for label, endpoint, _ in resource_types:
            futs[pool.submit(
                _paginate, source_session,
                f"{source_base_url}/orgs/{source_org_id}/{endpoint}"
            )] = (label, "source")
            futs[pool.submit(
                _paginate, dest_session,
                f"{dest_base_url}/orgs/{dest_org_id}/{endpoint}"
            )] = (label, "dest")

        for fut in as_completed(futs):
            label, side = futs[fut]
            all_data.setdefault(label, {})[side] = fut.result()

    ui.section("Sync Preview")
    total_missing = 0
    for label, _, name_key in resource_types:
        data = all_data.get(label, {})
        source_items = data.get("source", [])
        dest_items = data.get("dest", [])
        dest_names = {i.get(name_key) for i in dest_items if i.get(name_key)}
        missing = [i.get(name_key) for i in source_items if i.get(name_key) not in dest_names]
        total_missing += len(missing)

        if missing:
            preview = ", ".join(str(n) for n in missing[:5])
            suffix = f" … (+{len(missing) - 5} more)" if len(missing) > 5 else ""
            ui.warn(f"{label}: {len(missing)} missing  →  {preview}{suffix}")
        else:
            ui.ok(f"{label}: all {len(source_items)} present")

    print()
    if total_missing:
        ui.bullet("Total missing resources", str(total_missing))
    else:
        ui.ok("Destination org is fully in sync — nothing to do.")
    return total_missing


def sync_org_resources(source_session, dest_session, source_org_id, dest_org_id,
                       source_base_url, dest_base_url):
    """Create missing org-level resources in destination, with proper ID remapping."""

    def _sync(label, endpoint, strip_fields=None, name_key="name",
              payload_transform=None):
        if strip_fields is None:
            strip_fields = _ORG_RESOURCE_STRIP_FIELDS
        src = _paginate(source_session,
                        f"{source_base_url}/orgs/{source_org_id}/{endpoint}")
        dst = _paginate(dest_session,
                        f"{dest_base_url}/orgs/{dest_org_id}/{endpoint}")

        dest_by_name = {i.get(name_key): i.get("id") for i in dst if i.get(name_key)}
        id_map = {}
        for item in src:
            sid = item.get("id")
            sname = item.get(name_key)
            if sid and sname and sname in dest_by_name:
                id_map[sid] = dest_by_name[sname]

        missing = [i for i in src if i.get(name_key) not in dest_by_name]
        if not missing:
            ui.ok(f"{label}: all present.")
            return id_map

        create_url = f"{dest_base_url}/orgs/{dest_org_id}/{endpoint}"
        ok = 0
        for item in missing:
            old_id = item.get("id")
            payload = {k: v for k, v in item.items() if k not in strip_fields}
            if payload_transform:
                payload_transform(payload)
            try:
                resp = api_request(dest_session, "POST", create_url,
                                   payload=payload, ok_status=(200, 201))
                new_id = resp.json().get("id")
                if old_id and new_id:
                    id_map[old_id] = new_id
                ok += 1
            except Exception as exc:
                ui.warn(f"{label} '{item.get(name_key)}' skipped: {exc}")
        ui.ok(f"{label}: {ok}/{len(missing)} created.")
        return id_map

    ui.section("Syncing Org-Level Resources")

    sg_id_map = _sync("Site groups", "sitegroups")
    _sync("Services", "services")
    sp_id_map = _sync("Service policies", "servicepolicies")
    net_id_map = _sync("Networks", "networks")

    def _wlan_tmpl_xform(payload):
        applies = payload.get("applies")
        if isinstance(applies, dict) and "org_id" in applies:
            applies["org_id"] = dest_org_id
        exceptions = payload.get("exceptions")
        if isinstance(exceptions, dict):
            old_sg_ids = exceptions.get("sitegroup_ids") or []
            if old_sg_ids:
                exceptions["sitegroup_ids"] = [sg_id_map.get(s, s) for s in old_sg_ids]

    _sync("Switch templates", "networktemplates")
    _sync("RF templates", "rftemplates")
    wlan_tmpl_id_map = _sync("WLAN templates", "templates",
                             payload_transform=_wlan_tmpl_xform)

    def _org_wlan_xform(payload):
        old_tid = payload.get("template_id")
        if old_tid and old_tid in wlan_tmpl_id_map:
            payload["template_id"] = wlan_tmpl_id_map[old_tid]

    _sync("Org WLANs", "wlans",
          strip_fields=_ORG_WLAN_STRIP_FIELDS, name_key="ssid",
          payload_transform=_org_wlan_xform)

    def _wan_edge_xform(payload):
        old_svc = payload.get("service_policies") or []
        remapped = []
        for entry in old_svc:
            src_id = entry.get("servicepolicy_id")
            if src_id:
                remapped.append({**entry, "servicepolicy_id": sp_id_map.get(src_id, src_id)})
            else:
                remapped.append(entry)
        payload["service_policies"] = remapped
        if net_id_map:
            old_nets = payload.get("networks")
            if isinstance(old_nets, dict):
                payload["networks"] = {net_id_map.get(k, k): v for k, v in old_nets.items()}

    _sync("WAN Edge templates", "gatewaytemplates",
          payload_transform=_wan_edge_xform)
    _sync("Alarm templates", "alarmtemplates")

    ui.ok("Org resource sync complete.")
