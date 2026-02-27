import ui
from config import RunConfig, _select_api_profile, validate_config_vars, load_dest_config
from session import build_session, _paginate, DEFAULT_TIMEOUT
from prompts import prompt_input, prompt_yes_no, select_from_list
from mist.orgs import parse_superuser_details, format_superuser_details
from mist.templates import prompt_template_assignment_mode


def collect_superusers_for_guided_flow(existing_raw):
    existing_users = parse_superuser_details(existing_raw)
    selected_users = []

    if existing_users:
        ui.section("Super Users Found in Config")
        for index, user in enumerate(existing_users, start=1):
            display_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or "<no name>"
            ui.info(f"  {index}.  {user['email']}  ({display_name})")
        if prompt_yes_no("Use these super users?", default=True):
            selected_users.extend(existing_users)

    if not prompt_yes_no("Invite super users for this run?", default=bool(selected_users)):
        return ""

    while prompt_yes_no("Add a super user?", default=(len(selected_users) == 0)):
        email = prompt_input("Super user email")
        first_name = prompt_input("First name (optional)", allow_empty=True)
        last_name = prompt_input("Last name (optional)", allow_empty=True)
        selected_users.append({
            "email": email,
            "first_name": first_name,
            "last_name": last_name
        })

    return format_superuser_details(selected_users)


def try_list_orgs(session, base_url):
    endpoints = [
        f"{base_url}/self",
        f"{base_url}/orgs",
        f"{base_url}/self/orgs"
    ]

    last_error = None
    for url in endpoints:
        try:
            import requests as _requests
            response = session.get(url, timeout=DEFAULT_TIMEOUT)
            if response.status_code == 200:
                if url.endswith("/self"):
                    data = response.json()
                    privileges = data.get("privileges", [])
                    orgs = []
                    seen_orgs = set()
                    for privilege in privileges:
                        if privilege.get("scope") != "org":
                            continue
                        org_id = privilege.get("org_id")
                        name = privilege.get("name") or privilege.get("org_name")
                        if org_id and org_id not in seen_orgs:
                            orgs.append({"id": org_id, "name": name or org_id})
                            seen_orgs.add(org_id)
                    if orgs:
                        return orgs, None
                    last_error = f"{url} returned no org privileges to list."
                    continue

                return _paginate(session, url), None

            last_error = (
                f"{url} returned status {response.status_code}: {response.text[:300]}"
            )
        except Exception as exc:
            last_error = f"{url} network/API error: {exc}"

    return None, last_error


def try_list_sites(session, base_url, org_id):
    endpoints = [
        f"{base_url}/orgs/{org_id}/sites",
        f"{base_url}/self"
    ]

    last_error = None
    for url in endpoints:
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT)
            if response.status_code == 200:
                if url.endswith("/self"):
                    data = response.json()
                    privileges = data.get("privileges", [])
                    sites = []
                    seen_sites = set()
                    for privilege in privileges:
                        if privilege.get("scope") != "site":
                            continue
                        if privilege.get("org_id") != org_id:
                            continue
                        site_id = privilege.get("site_id")
                        name = privilege.get("name")
                        if site_id and site_id not in seen_sites:
                            sites.append({"id": site_id, "name": name or site_id})
                            seen_sites.add(site_id)
                    if sites:
                        return sites, None
                    last_error = f"{url} returned no site privileges to list for org {org_id}."
                    continue

                return _paginate(session, url), None

            last_error = (
                f"{url} returned status {response.status_code}: {response.text[:300]}"
            )
        except Exception as exc:
            last_error = f"{url} network/API error: {exc}"

    return None, last_error


def collect_run_details(session, base_url, cfg: RunConfig):
    ui.section("Step 2 — Source Configuration")
    orgs, org_error = try_list_orgs(session, base_url)
    if orgs is not None:
        cfg.source_organization_id = select_from_list(orgs, "orgs") or ""
    else:
        ui.warn(f"Unable to list orgs: {org_error}")

    if not cfg.source_organization_id:
        cfg.source_organization_id = prompt_input("Source organization ID")

    sites, site_error = try_list_sites(session, base_url, cfg.source_organization_id)
    if sites is None:
        ui.warn(f"Unable to list sites: {site_error}")
        sites = []

    ui.menu("Site Clone Mode", [
        ("1", "Clone a single site"),
        ("2", "Clone all sites in the org"),
    ])
    site_mode = prompt_input("Select option", default="1")

    selected_sites = []
    if site_mode == "2" and sites:
        selected_sites = sites
    else:
        if sites:
            chosen_id = select_from_list(sites, "sites")
            if chosen_id:
                selected_sites = [site for site in sites if site.get("id") == chosen_id]
        if not selected_sites:
            manual_id = prompt_input("Source site ID")
            selected_sites = [{"id": manual_id, "name": manual_id}]

    cfg.source_site_id = selected_sites[0]["id"]
    cfg.new_organization_name = prompt_input("New organization name")
    cfg.new_superuser_details = collect_superusers_for_guided_flow("")

    site_plans = []
    batch_keep_details = None
    if len(selected_sites) > 1:
        ui.section("Configure Sites — Batch Option")
        ui.info(f"  {len(selected_sites)} sites selected.")
        use_all = prompt_yes_no("Use source site name/address for ALL sites?", default=True)
        if use_all:
            batch_keep_details = True
        else:
            per_site = prompt_yes_no("Configure name/address individually per site?", default=True)
            if not per_site:
                batch_keep_details = False

    for site in selected_sites:
        source_site_id = site.get("id")
        source_name = site.get("name") or source_site_id
        source_address = site.get("address") or ""
        source_country_code = site.get("country_code") or ""
        ui.section(f"Configure Site — {source_name}  ({source_site_id})")
        if batch_keep_details is not None:
            keep_details = batch_keep_details
            label = "source" if keep_details else "custom"
            ui.info(f"  Using {label} site name/address (batch selection).")
        else:
            keep_details = prompt_yes_no("Use source site name/address?", default=True)
        if keep_details:
            new_site_name = source_name
            new_site_address = source_address or prompt_input("New site address")
        else:
            new_site_name = prompt_input("New site name")
            new_site_address = prompt_input("New site address")

        if keep_details and source_country_code:
            country_code = source_country_code
        else:
            country_code = prompt_input("Country code", default=source_country_code or "US")
        site_plans.append({
            "source_site_id": source_site_id,
            "source_site_name": source_name,
            "new_site_name": new_site_name,
            "new_site_address": new_site_address,
            "country_code": country_code
        })

    cfg.site_plans = site_plans
    cfg.site_clone_mode = site_mode
    cfg.template_assignment_mode = prompt_template_assignment_mode()


def guided_flow(args):
    import json
    from preflight import build_preflight_report, preflight_summary, build_preflight_markdown
    from workflow import run_clone_flow, _setup_dest_context, _offer_save_log

    ui.start_log()
    ui.banner("Mist Org Clone Tool", "Guided Setup")
    ui.section("Step 1 — Source API Configuration")

    selected_section_name, config_dict = _select_api_profile("Select Cloud Instance")
    cfg = RunConfig.from_dict(config_dict)

    validate_config_vars(cfg)
    source_base_url = cfg.base_url
    source_headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Token {cfg.api_token}'
    }
    source_session = build_session(extra_headers=source_headers)

    dest_session, dest_base_url, cross_cloud = _setup_dest_context(source_session, source_base_url)

    collect_run_details(source_session, source_base_url, cfg)

    template_name_map = {
        "switch_template_id": cfg.switch_template_name,
        "wan_edge_template_id": cfg.wan_edge_template_name,
        "wlan_template_id": cfg.wlan_template_name,
        "rftemplate_id": cfg.rf_template_name
    }

    preflight_report = build_preflight_report(
        source_session, cfg.source_organization_id,
        cfg.source_site_id, template_name_map,
        cfg=cfg,
        source_base_url=source_base_url,
    )
    preflight_summary(preflight_report, template_assignment_mode=cfg.template_assignment_mode)

    if cross_cloud:
        ui.bullet("Clone mode", f"Cross-cloud  →  {dest_base_url}")
    else:
        ui.bullet("Clone mode", "Same cloud instance")

    ui.section("Step 3 — Preflight Options")
    report_path = args.preflight_json or args.preflight
    if report_path is None:
        write_report = prompt_yes_no("Save preflight report to file?", default=True)
        if write_report:
            fmt = prompt_input("Format? Enter 'md' for Markdown or 'json' for JSON", default="md")
            if fmt.strip().lower() == "json":
                report_path = prompt_input("Report filename", default="preflight_report.json")
            else:
                report_path = prompt_input("Report filename", default="preflight_report.md")
    if report_path:
        if report_path.endswith(".md") or args.preflight:
            md_content = build_preflight_markdown(preflight_report,
                                                  template_assignment_mode=cfg.template_assignment_mode)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(md_content)
        else:
            with open(report_path, "w", encoding="utf-8") as file:
                json.dump(preflight_report, file, indent=2, sort_keys=True)
        ui.ok(f"Preflight report written to {report_path}")

    if args.dry_run:
        ui.info("Dry-run mode — no changes applied.")
        _offer_save_log()
        return

    proceed = prompt_yes_no("Proceed with cloning and site creation?", default=False)
    if not proceed:
        ui.info("Aborted — no changes applied.")
        _offer_save_log()
        return

    run_clone_flow(source_session, dest_session, source_base_url, dest_base_url,
                   template_name_map, cfg=cfg, cross_cloud=cross_cloud)
    _offer_save_log()
