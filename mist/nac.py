import ui
from session import api_request, _paginate
from mist import _ORG_RESOURCE_STRIP_FIELDS
from prompts import prompt_yes_no


def _remap_ids_recursive(obj, id_map):
    if isinstance(obj, dict):
        return {k: _remap_ids_recursive(v, id_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remap_ids_recursive(item, id_map) for item in obj]
    if isinstance(obj, str) and obj in id_map:
        return id_map[obj]
    return obj


def clone_nac_sso_roles(source_session, dest_session, source_org_id, dest_org_id,
                        source_base_url, dest_base_url):
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/ssoroles")
    except Exception as exc:
        ui.warn(f"Could not fetch SSO roles: {exc}")
        return {}
    if not items:
        ui.info("No SSO roles found in source org.")
        return {}
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/ssoroles"
    id_map = {}
    ok = 0
    for item in items:
        old_id = item.get("id")
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            resp = api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                id_map[old_id] = new_id
            ok += 1
        except Exception as exc:
            ui.warn(f"SSO role '{item.get('name')}' skipped: {exc}")
    ui.ok(f"SSO roles copied: {ok}/{len(items)}")
    return id_map


def clone_nac_ssos(source_session, dest_session, source_org_id, dest_org_id,
                   ssorole_id_map, source_base_url, dest_base_url):
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/ssos")
    except Exception as exc:
        ui.warn(f"Could not fetch SSOs: {exc}")
        return {}
    if not items:
        ui.info("No SSOs found in source org.")
        return {}
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/ssos"
    id_map = {}
    ok = 0
    names = []
    for item in items:
        old_id = item.get("id")
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        if ssorole_id_map:
            payload = _remap_ids_recursive(payload, ssorole_id_map)
        try:
            resp = api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                id_map[old_id] = new_id
            ok += 1
            names.append(item.get("name") or old_id or "unknown")
        except Exception as exc:
            ui.warn(f"SSO '{item.get('name')}' skipped: {exc}")
    ui.ok(f"SSOs copied: {ok}/{len(items)}")
    if names:
        ui.warn("ACTION REQUIRED — SSO / SAML SP metadata must be reconfigured:")
        ui.info("  Each SSO generates a unique Service Provider (SP) entity per org.")
        ui.info("  The SP Entity ID, ACS URL, and signing certificate are different in the")
        ui.info("  destination org and must be re-registered with your Identity Provider.")
        ui.info("  For each SSO below, retrieve the new SP metadata and update your IdP:")
        ui.info("    Mist UI → Organization → Access → SSOs → (select SSO) → Download SP Metadata")
        for name in names:
            ui.info(f"    • {name}")
        ui.warn("ACTION REQUIRED — SSO / IDP Allowable Domains not cloned:")
        ui.info("  The 'Allowable Domains' list for each SSO / IDP configuration is not")
        ui.info("  included in the /ssos endpoint payload and must be reconfigured manually")
        ui.info("  in the destination org for each SSO listed above:")
        ui.info("    Mist UI → Organization → Access → SSOs → (select SSO) → Allowable Domains")
    return id_map


def clone_nac_settings(source_session, dest_session, source_org_id, dest_org_id,
                       source_base_url, dest_base_url):
    try:
        source_settings = api_request(
            source_session, "GET", f"{source_base_url}/orgs/{source_org_id}/setting"
        ).json()
    except Exception as exc:
        ui.warn(f"Could not fetch org settings for NAC copy: {exc}")
        return
    mist_nac = source_settings.get("mist_nac")
    if not mist_nac:
        ui.info("No mist_nac block found in source org settings — skipping.")
        return
    try:
        api_request(
            dest_session, "PUT", f"{dest_base_url}/orgs/{dest_org_id}/setting",
            payload={"mist_nac": mist_nac}, ok_status=(200, 201)
        )
        ui.ok("NAC org settings (mist_nac) copied.")
        ui.warn("ACTION REQUIRED — RADIUS shared secrets and IDP credentials:")
        ui.info("  The mist_nac block (RADIUS servers, IDP config) has been copied to the")
        ui.info("  destination org. RADIUS shared secrets and IDP credentials are included.")
        ui.info("  Verify that all secrets are correct for the destination environment:")
        ui.info("    Mist UI → Organization → Access → Access Assurance → Settings")
        ui.info("  Update any RADIUS shared secrets that differ between environments.")
    except Exception as exc:
        ui.warn(f"Could not copy mist_nac settings: {exc}")


def clone_nac_scep(source_session, dest_session, source_org_id, dest_org_id,
                   source_base_url, dest_base_url):
    try:
        scep = api_request(
            source_session, "GET", f"{source_base_url}/orgs/{source_org_id}/setting/mist_scep"
        ).json()
    except Exception:
        ui.info("SCEP settings not found or not accessible — skipping.")
        return
    if not scep.get("enabled"):
        ui.info("SCEP is not enabled in source org — skipping.")
        return
    try:
        api_request(
            dest_session, "PUT", f"{dest_base_url}/orgs/{dest_org_id}/setting/mist_scep",
            payload=scep, ok_status=(200, 201)
        )
        ui.ok("SCEP configuration copied.")
        ui.warn("ACTION REQUIRED — SCEP Certificate Authority (CA):")
        ui.info("  SCEP config has been copied but the Certificate Authority is org-specific.")
        ui.info("  A new CA will be generated for the destination org automatically.")
        ui.info("  Client devices will need to trust the new CA certificate.")
        ui.info("  Download and distribute the new CA cert from:")
        ui.info("    Mist UI → Organization → Access → Access Assurance → SCEP → Download CA Cert")
    except Exception as exc:
        ui.warn(f"Could not copy SCEP settings: {exc}")


def clone_nac_tags(source_session, dest_session, source_org_id, dest_org_id,
                   source_base_url, dest_base_url):
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/nactags")
    except Exception as exc:
        ui.warn(f"Could not fetch NAC tags: {exc}")
        return {}
    if not items:
        ui.info("No NAC tags found in source org.")
        return {}
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/nactags"
    id_map = {}
    ok = 0
    for item in items:
        old_id = item.get("id")
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            resp = api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            new_id = resp.json().get("id")
            if old_id and new_id:
                id_map[old_id] = new_id
            ok += 1
        except Exception as exc:
            ui.warn(f"NAC tag '{item.get('name')}' skipped: {exc}")
    ui.ok(f"NAC tags copied: {ok}/{len(items)}")
    return id_map


def clone_nac_rules(source_session, dest_session, source_org_id, dest_org_id,
                    nactag_id_map, source_base_url, dest_base_url):
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/nacrules")
    except Exception as exc:
        ui.warn(f"Could not fetch NAC rules: {exc}")
        return
    if not items:
        ui.info("No NAC rules found in source org.")
        return
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/nacrules"
    ok = 0
    for item in items:
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        if nactag_id_map:
            payload = _remap_ids_recursive(payload, nactag_id_map)
        try:
            api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok += 1
        except Exception as exc:
            ui.warn(f"NAC rule '{item.get('name')}' skipped: {exc}")
    ui.ok(f"NAC rules copied: {ok}/{len(items)}")


def clone_nac_portals(source_session, dest_session, source_org_id, dest_org_id,
                      nactag_id_map, sso_id_map, source_base_url, dest_base_url):
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/nacportals")
    except Exception as exc:
        ui.warn(f"Could not fetch NAC portals: {exc}")
        return
    if not items:
        ui.info("No NAC portals found in source org.")
        return
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/nacportals"
    ok = 0
    names = []
    combined_id_map = {**nactag_id_map, **sso_id_map}
    for item in items:
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        if combined_id_map:
            payload = _remap_ids_recursive(payload, combined_id_map)
        try:
            api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok += 1
            names.append(item.get("name") or item.get("id") or "unknown")
        except Exception as exc:
            ui.warn(f"NAC portal '{item.get('name')}' skipped: {exc}")
    ui.ok(f"NAC portals copied: {ok}/{len(items)}")
    if names:
        ui.warn("ACTION REQUIRED — NAC Portal post-clone steps required:")
        ui.info("")
        ui.info("  1. PORTAL BRANDING IMAGES cannot be transferred via the API.")
        ui.info("     Re-upload any custom logo or background images for each portal:")
        ui.info("       Mist UI → Organization → Access → NAC Portals → (select portal) → Branding")
        ui.info("")
        ui.info("  2. SAML SP METADATA is unique per org — the destination portal has a new")
        ui.info("     SP Entity ID, ACS URL, and signing certificate.")
        ui.info("     Retrieve the new SP metadata and update your IdP for each portal below:")
        ui.info("       Mist UI → Organization → Access → NAC Portals → (select portal) → Download SP Metadata")
        ui.info("")
        for name in names:
            ui.info(f"    • {name}")


def clone_psk_portals(source_session, dest_session, source_org_id, dest_org_id,
                      source_base_url, dest_base_url):
    _PSK_EXTRA_STRIP = {"ui_url"}
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/pskportals")
    except Exception as exc:
        ui.warn(f"Could not fetch PSK portals: {exc}")
        return
    if not items:
        ui.info("No PSK portals found in source org.")
        return
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/pskportals"
    ok_count = 0
    names = []
    sso_names = []
    image_names = []
    for item in items:
        payload = {
            k: v for k, v in item.items()
            if k not in _ORG_RESOURCE_STRIP_FIELDS and k not in _PSK_EXTRA_STRIP
        }
        portal_name = item.get("name") or item.get("id") or "unknown"
        try:
            api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok_count += 1
            names.append(portal_name)
            if item.get("auth") == "sso" or item.get("sso"):
                sso_names.append(portal_name)
            if any(item.get(f) for f in ("bg_image_url", "thumbnail_url", "template_url")):
                image_names.append(portal_name)
        except Exception as exc:
            ui.warn(f"PSK portal '{portal_name}' skipped: {exc}")
    ui.ok(f"PSK portals copied: {ok_count}/{len(items)}")
    if sso_names:
        ui.warn("ACTION REQUIRED \u2014 PSK Portal SSO / SAML SP metadata must be reconfigured:")
        ui.info("  Each PSK portal with SSO auth generates a unique SP Entity ID and ACS URL.")
        ui.info("  Retrieve the new SP metadata for each portal below and re-register with your IdP:")
        ui.info("    Mist UI \u2192 Organization \u2192 Access \u2192 PSK Portals \u2192 (select portal) \u2192 Download SP Metadata")
        for name in sso_names:
            ui.info(f"    \u2022 {name}")
    if image_names:
        ui.warn("ACTION REQUIRED \u2014 PSK Portal branding images must be re-uploaded:")
        ui.info("  Background images, thumbnails, and custom templates are binary uploads")
        ui.info("  that cannot be transferred via the API. Re-upload them for each portal below:")
        ui.info("    Mist UI \u2192 Organization \u2192 Access \u2192 PSK Portals \u2192 (select portal) \u2192 Branding")
        for name in image_names:
            ui.info(f"    \u2022 {name}")


def clone_nac_crl_notice():
    ui.warn("ACTION REQUIRED — Certificate Revocation Lists (CRLs):")
    ui.info("  CRL files are uploaded binary files and cannot be transferred automatically.")
    ui.info("  If the source org has CRLs configured, re-upload them to the destination org:")
    ui.info("    Mist UI → Organization → Access → Access Assurance → Certificates → Upload CRL")


def clone_user_macs(source_session, dest_session, source_org_id, dest_org_id,
                    source_base_url, dest_base_url):
    if not prompt_yes_no("Clone User MAC entries (endpoint identities with labels)?", default=False):
        ui.info("User MAC entries skipped.")
        return
    try:
        items = _paginate(source_session, f"{source_base_url}/orgs/{source_org_id}/usermacs")
    except Exception as exc:
        ui.warn(f"Could not fetch User MACs: {exc}")
        return
    if not items:
        ui.info("No User MAC entries found in source org.")
        return
    create_url = f"{dest_base_url}/orgs/{dest_org_id}/usermacs"
    ok = 0
    for item in items:
        payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok += 1
        except Exception as exc:
            ui.warn(f"User MAC '{item.get('mac')}' skipped: {exc}")
    ui.ok(f"User MAC entries copied: {ok}/{len(items)}")


def clone_nac(source_session, dest_session, source_org_id, dest_org_id,
              source_base_url, dest_base_url):
    ui.progress("Copying NAC org settings …")
    clone_nac_settings(
        source_session, dest_session, source_org_id, dest_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying SCEP configuration …")
    clone_nac_scep(
        source_session, dest_session, source_org_id, dest_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying SSO roles …")
    ssorole_id_map = clone_nac_sso_roles(
        source_session, dest_session, source_org_id, dest_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying SSOs …")
    sso_id_map = clone_nac_ssos(
        source_session, dest_session, source_org_id, dest_org_id,
        ssorole_id_map,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying NAC tags …")
    nactag_id_map = clone_nac_tags(
        source_session, dest_session, source_org_id, dest_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying NAC rules …")
    clone_nac_rules(
        source_session, dest_session, source_org_id, dest_org_id,
        nactag_id_map,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying NAC portals …")
    clone_nac_portals(
        source_session, dest_session, source_org_id, dest_org_id,
        nactag_id_map, sso_id_map,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    ui.progress("Copying PSK portals …")
    clone_psk_portals(
        source_session, dest_session, source_org_id, dest_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    clone_nac_crl_notice()

    clone_user_macs(
        source_session, dest_session, source_org_id, dest_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )
