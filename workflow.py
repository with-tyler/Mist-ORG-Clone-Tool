from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import ui
from config import RunConfig, validate_config_vars, load_dest_config
from session import build_session, api_request
from prompts import prompt_input, prompt_yes_no
from mist.orgs import clone_organization, invite_super_users, fetch_alarm_templates, clone_alarm_templates
from mist.sites import (create_site, copy_site_settings, clone_site_wlans,
                        clone_site_maps, get_site_details, _prefetch_source_site_data)
from mist.templates import (
    build_template_maps, build_wlan_scope_info, build_new_template_id_map,
    normalize_template_ids, derive_source_site_template_ids,
    resolve_template_ids_from_source, compute_mode4_skip_reasons,
    format_template_skip_warnings, format_assigned_template_names,
    assign_templates, finalize_wlan_assignments, prompt_template_choices_for_org,
)
from mist.sitegroups import fetch_sitegroups, build_sitegroup_name_to_id, clone_sitegroup_membership
from mist.nac import clone_nac
from mist.cross_cloud import cross_cloud_bootstrap_org, remap_gateway_template_service_policies


def run_clone_flow(source_session, dest_session, source_base_url, dest_base_url,
                   template_name_map, cfg: RunConfig, cross_cloud=False):
    ui.section("Step 4 — Cloning Organization")

    if cross_cloud:
        ui.progress("Bootstrapping organization on destination cloud …")
        new_org_id = cross_cloud_bootstrap_org(
            source_session, dest_session,
            cfg.source_organization_id,
            cfg.new_organization_name,
            source_base_url, dest_base_url,
        )
        ui.ok(f"Organization bootstrapped on destination  →  ID: {new_org_id}")
    else:
        ui.progress("Cloning organization structure …")
        new_org_id = clone_organization(
            source_session,
            cfg.source_organization_id,
            cfg.new_organization_name,
            source_base_url=source_base_url,
        )
        ui.ok(f"Organization cloned  →  ID: {new_org_id}")
        remap_gateway_template_service_policies(
            source_session, cfg.source_organization_id, new_org_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
            dest_session=dest_session,
        )
        ui.section("Alarm Templates")
        clone_alarm_templates(
            source_session, dest_session,
            cfg.source_organization_id, new_org_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
        )

    ui.section("Access Assurance (NAC)")
    if ui.ask_yn("Clone Access Assurance (NAC) configuration?", default=True):
        clone_nac(
            source_session, dest_session,
            cfg.source_organization_id, new_org_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
        )
    else:
        ui.info("NAC cloning skipped.")

    source_maps, new_maps, new_templates = build_template_maps(
        source_session,
        cfg.source_organization_id,
        new_org_id,
        source_base_url=source_base_url,
        dest_base_url=dest_base_url,
        dest_session=dest_session,
    )
    new_id_name_map = build_new_template_id_map(new_templates)

    source_alarm_templates = fetch_alarm_templates(
        source_session, cfg.source_organization_id, base_url=source_base_url
    )
    new_alarm_templates = fetch_alarm_templates(dest_session, new_org_id, base_url=dest_base_url)
    source_alarm_id_to_name = {t.get("id"): t.get("name") for t in source_alarm_templates if t.get("id")}
    new_alarm_name_to_id = {t.get("name"): t.get("id") for t in new_alarm_templates if t.get("name")}

    _, new_org_wlan_org_ids = build_wlan_scope_info(dest_session, new_org_id, base_url=dest_base_url)

    source_sitegroups = fetch_sitegroups(
        source_session, cfg.source_organization_id, base_url=source_base_url
    )
    new_sitegroups = fetch_sitegroups(dest_session, new_org_id, base_url=dest_base_url)
    new_sitegroup_name_to_id = build_sitegroup_name_to_id(new_sitegroups)
    if source_sitegroups:
        ui.info(f"Site groups: {len(source_sitegroups)} in source, {len(new_sitegroups)} in new org.")

    assignment_mode = cfg.template_assignment_mode
    global_template_ids = {}
    per_site_apply_all = False
    per_site_template_ids = {}
    wlan_site_map = {}
    wlan_org_level_ids: set = set()
    site_level_wlan_map: dict = {}
    org_level_wlan_ids_new: set = set()

    if assignment_mode == "4":
        wlan_site_map, wlan_org_level_ids = build_wlan_scope_info(
            source_session, cfg.source_organization_id, base_url=source_base_url
        )

    if assignment_mode in {"2", "3"}:
        ui.section("Template Selection (applies to all sites)")
        name_choices = prompt_template_choices_for_org(new_templates)
        for key, name in name_choices.items():
            new_id = new_maps.get(key, {}).get(name)
            if not new_id:
                continue
            if key == "wlan" and new_id in new_org_wlan_org_ids:
                global_template_ids["wlan_org"] = new_id
            else:
                global_template_ids[key] = new_id
    elif assignment_mode == "1":
        per_site_apply_all = prompt_yes_no(
            "Use the same template selection for all sites?",
            default=False
        )
        if per_site_apply_all:
            ui.section("Template Selection (applies to all sites)")
            name_choices = prompt_template_choices_for_org(new_templates)
            for key, name in name_choices.items():
                new_id = new_maps.get(key, {}).get(name)
                if not new_id:
                    continue
                if key == "wlan" and new_id in new_org_wlan_org_ids:
                    per_site_template_ids["wlan_org"] = new_id
                else:
                    per_site_template_ids[key] = new_id

    site_plans = cfg.site_plans

    pre_fetched: dict = {}
    if site_plans:
        ui.progress(f"Pre-fetching source data for {len(site_plans)} site(s) …")
        with ThreadPoolExecutor(max_workers=min(len(site_plans), 10)) as pool:
            futs = {
                pool.submit(
                    _prefetch_source_site_data,
                    source_session,
                    sp["source_site_id"],
                    source_base_url,
                ): sp["source_site_id"]
                for sp in site_plans
            }
            for fut in as_completed(futs):
                sid = futs[fut]
                try:
                    pre_fetched[sid] = fut.result()
                except Exception as exc:
                    pre_fetched[sid] = {}
                    ui.warn(f"Pre-fetch failed for source site {sid}: {exc}")
        ui.ok(f"Source site data pre-fetched for {len(pre_fetched)} site(s).")

    for site_plan in site_plans:
        cached = pre_fetched.get(site_plan["source_site_id"], {})
        skip_reasons = {}
        ui.section(f"Site  →  {site_plan['new_site_name']}")
        ui.progress(f"Creating site '{site_plan['new_site_name']}' …")
        new_site_id = create_site(
            dest_session,
            new_org_id,
            site_plan["new_site_name"],
            site_plan["new_site_address"],
            site_plan["country_code"],
            base_url=dest_base_url,
        )
        ui.ok(f"Site created  →  ID: {new_site_id}")

        ui.progress("Copying site settings …")
        copy_site_settings(
            source_session, site_plan["source_site_id"], new_site_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
            dest_session=dest_session,
            _cached_settings=cached.get("settings"),
        )
        ui.ok("Site settings copied.")

        ui.progress("Copying site-specific WLANs …")
        wlan_count = clone_site_wlans(
            source_session, dest_session,
            site_plan["source_site_id"], new_site_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
            _cached_wlans=cached.get("wlans"),
        )
        if wlan_count:
            ui.ok(f"Site-specific WLANs copied: {wlan_count}")
        else:
            ui.info("No site-specific WLANs found.")

        ui.progress("Copying site floor plan maps …")
        maps_count = clone_site_maps(
            source_session, dest_session,
            site_plan["source_site_id"], new_site_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
            _cached_maps=cached.get("maps"),
        )
        if maps_count:
            ui.ok(f"Site maps copied: {maps_count}")
        else:
            ui.info("No site maps found.")

        source_site_details_for_sg = (
            cached.get("details")
            or get_site_details(source_session, site_plan["source_site_id"], base_url=source_base_url)
        )
        unmatched_sitegroups = clone_sitegroup_membership(
            dest_session,
            source_site_details_for_sg,
            source_sitegroups,
            new_sitegroup_name_to_id,
            new_org_id,
            new_site_id,
            base_url=dest_base_url,
        )
        matched_sg_count = len((source_site_details_for_sg.get("sitegroup_ids") or [])) - len(unmatched_sitegroups)
        if matched_sg_count > 0:
            ui.ok(f"Site group membership applied: {matched_sg_count} group(s).")
        if unmatched_sitegroups:
            ui.warn(f"Unmatched site groups for '{site_plan['new_site_name']}': {', '.join(str(x) for x in unmatched_sitegroups)}")

        source_alarm_id = source_site_details_for_sg.get("alarmtemplate_id")
        if source_alarm_id:
            alarm_name = source_alarm_id_to_name.get(source_alarm_id)
            new_alarm_id = new_alarm_name_to_id.get(alarm_name) if alarm_name else None
            if new_alarm_id:
                alarm_url = f'{dest_base_url}/sites/{new_site_id}'
                api_request(dest_session, "PUT", alarm_url, payload={"alarmtemplate_id": new_alarm_id})
                ui.ok(f"Alarm template '{alarm_name}' assigned.")
            else:
                ui.warn(f"Alarm template ID '{source_alarm_id}' could not be remapped — no matching name found in new org.")

        if assignment_mode == "4":
            source_site_details = source_site_details_for_sg
            source_template_ids = derive_source_site_template_ids(
                source_site_details,
                site_id=site_plan["source_site_id"],
                wlan_site_map=wlan_site_map,
                wlan_org_level_ids=wlan_org_level_ids,
            )
            resolved_template_ids = resolve_template_ids_from_source(
                source_site_details,
                source_maps,
                new_maps,
                site_id=site_plan["source_site_id"],
                wlan_site_map=wlan_site_map,
                wlan_org_level_ids=wlan_org_level_ids,
            )
            template_ids = resolved_template_ids
            skip_reasons = compute_mode4_skip_reasons(
                source_template_ids,
                resolved_template_ids,
                source_maps
            )
        elif assignment_mode == "1":
            if per_site_apply_all:
                template_ids = per_site_template_ids
            else:
                ui.section(f"Template Selection — {site_plan['new_site_name']}")
                choices = prompt_template_choices_for_org(new_templates)
                template_ids = {}
                for key, name in choices.items():
                    new_id = new_maps.get(key, {}).get(name)
                    if not new_id:
                        continue
                    if key == "wlan" and new_id in new_org_wlan_org_ids:
                        template_ids["wlan_org"] = new_id
                    else:
                        template_ids[key] = new_id
        else:
            template_ids = global_template_ids

        template_ids = normalize_template_ids(template_ids)

        site_wlan = template_ids.pop("wlan_template_id", None)
        org_wlan  = template_ids.pop("wlan_org_template_id", None)

        if site_wlan:
            for tid in (site_wlan if isinstance(site_wlan, list) else [site_wlan]):
                site_level_wlan_map.setdefault(tid, []).append(new_site_id)

        if org_wlan:
            for tid in (org_wlan if isinstance(org_wlan, list) else [org_wlan]):
                org_level_wlan_ids_new.add(tid)

        if not any(template_ids.values()):
            ui.info("No non-WLAN templates selected for assignment.")
        else:
            ui.progress("Assigning non-WLAN templates …")
            assign_templates(dest_session, new_org_id, new_site_id, template_ids,
                             base_url=dest_base_url)

        display_ids = dict(template_ids)
        if site_wlan:
            display_ids["wlan_template_id"] = site_wlan
        if org_wlan:
            display_ids["wlan_org_template_id"] = org_wlan
        if display_ids:
            assigned_names = format_assigned_template_names(display_ids, new_id_name_map)
            ui.info(f"Deferred WLAN + non-WLAN plan: {assigned_names}")

        if skip_reasons:
            warning_summary = format_template_skip_warnings(skip_reasons)
            ui.warn(f"Template assignment warnings: {warning_summary}")

    finalize_wlan_assignments(
        dest_session,
        new_org_id,
        site_level_wlan_map,
        org_level_wlan_ids_new,
        new_id_name_map,
        base_url=dest_base_url,
    )

    if cfg.new_superuser_details:
        ui.progress("Inviting super users …")
        invite_super_users(dest_session, new_org_id, cfg.new_superuser_details,
                           base_url=dest_base_url)
        ui.ok("Super users invited to new organization.")
    else:
        ui.info("No super users invited — none selected for this run.")


def _setup_dest_context(source_session, source_base_url):
    ui.section("Step 1b — Destination Instance")
    ui.menu("Clone Mode", [
        ("1", "Same cloud instance (default)"),
        ("2", "Different cloud instance (cross-cloud)"),
    ])
    mode = prompt_input("Select option", default="1")

    if mode == "2":
        dest_section_name, dest_vars = load_dest_config()
        dest_cfg = RunConfig.from_dict(dest_vars)
        validate_config_vars(dest_cfg)
        dest_headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {dest_cfg.api_token}'
        }
        dest_session = build_session(extra_headers=dest_headers)
        dest_base_url = dest_cfg.base_url
        ui.ok(f"Destination: {dest_section_name}  ({dest_base_url})")
        return dest_session, dest_base_url, True

    return source_session, source_base_url, False


def _write_run_log(path: str) -> None:
    lines = ui.get_log_lines()
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Mist Org Clone — Run Log\n\n")
        f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
        f.write("---\n\n")
        for line in lines:
            f.write(line + "\n")
    ui.ok(f"Run log saved to {path}")


def _offer_save_log() -> None:
    if ui.ask_yn("Save a full run log to a Markdown file?", default=True):
        log_path = ui.ask("Log filename", default="clone_log.md")
        _write_run_log(log_path)
