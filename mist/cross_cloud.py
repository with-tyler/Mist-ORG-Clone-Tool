from concurrent.futures import ThreadPoolExecutor, as_completed

import ui
from session import api_request, _paginate
from mist import _ORG_RESOURCE_STRIP_FIELDS
from mist.sitegroups import fetch_sitegroups
from mist.orgs import fetch_alarm_templates, clone_alarm_templates

_SERVICEPOLICY_STRIP_FIELDS = {"id", "org_id", "created_time", "modified_time"}


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
    sg_ok = 0
    for sg in source_sgs:
        payload = {k: v for k, v in sg.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            api_request(dest_session, "POST", sg_url, payload=payload, ok_status=(200, 201))
            sg_ok += 1
        except Exception as exc:
            ui.warn(f"Sitegroup '{sg.get('name')}' skipped: {exc}")
    ui.ok(f"Site groups copied: {sg_ok}/{len(source_sgs)}")

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

    parallel_tasks = [
        ("Switch",  "networktemplates"),
        ("RF",      "rftemplates"),
        ("WLAN",    "templates"),
    ]

    def _copy_template_type(label, endpoint):
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/{endpoint}")
        create_url = f"{dest_base_url}/orgs/{new_org_id}/{endpoint}"
        t_ok = 0
        for item in items:
            payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
            try:
                api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
                t_ok += 1
            except Exception as exc:
                ui.warn(f"{label} template '{item.get('name')}' skipped: {exc}")
        return label, t_ok, len(items)

    ui.progress("Copying Switch, RF and WLAN templates in parallel …")
    with ThreadPoolExecutor(max_workers=3) as _ex:
        _template_futures = {_ex.submit(_copy_template_type, lbl, ep): lbl
                             for lbl, ep in parallel_tasks}
        for _future in as_completed(_template_futures):
            _lbl, _t_ok, _total = _future.result()
            ui.ok(f"{_lbl} templates copied: {_t_ok}/{_total}")

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
