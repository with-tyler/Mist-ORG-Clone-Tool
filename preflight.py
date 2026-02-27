from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import ui
from session import _paginate
from mist.sites import get_site_settings, get_site_details
from mist.sitegroups import fetch_sitegroups
from mist.templates import (
    build_template_maps, build_wlan_scope_info,
    derive_source_site_template_ids, resolve_template_ids_from_source,
    compute_mode4_skip_reasons, format_template_skip_warnings,
)


def summarize_list(items, label, max_items=5):
    ui.summarize_list(items, label, max_items=max_items)


def build_preflight_report(session, source_org_id, source_site_id, template_name_map,
                           cfg, source_base_url):
    site_plans = cfg.site_plans
    template_assignment_mode = cfg.template_assignment_mode

    _fetch_tasks = {
        "settings":           lambda: get_site_settings(session, source_site_id, base_url=source_base_url),
        "switch_templates":   lambda: _paginate(session, f'{source_base_url}/orgs/{source_org_id}/networktemplates'),
        "wan_edge_templates": lambda: _paginate(session, f'{source_base_url}/orgs/{source_org_id}/gatewaytemplates'),
        "wlan_templates":     lambda: _paginate(session, f'{source_base_url}/orgs/{source_org_id}/templates'),
        "rf_templates":       lambda: _paginate(session, f'{source_base_url}/orgs/{source_org_id}/rftemplates'),
        "service_policies":   lambda: _paginate(session, f'{source_base_url}/orgs/{source_org_id}/servicepolicies'),
        "sitegroups":         lambda: fetch_sitegroups(session, source_org_id, base_url=source_base_url),
    }
    _results: dict = {}
    with ThreadPoolExecutor(max_workers=len(_fetch_tasks)) as _ex:
        _futures = {_ex.submit(fn): key for key, fn in _fetch_tasks.items()}
        for _future in as_completed(_futures):
            _results[_futures[_future]] = _future.result()

    site_settings = _results["settings"]
    settings_keys = sorted(site_settings.keys())
    vars_count = len(site_settings.get("vars", {})) if isinstance(site_settings.get("vars"), dict) else 0

    templates = {
        label: [{"id": i.get("id"), "name": i.get("name")} for i in _results[label]]
        for label in ("switch_templates", "wan_edge_templates", "wlan_templates", "rf_templates")
    }
    service_policies = [
        {"id": i.get("id"), "name": i.get("name")} for i in _results["service_policies"]
    ]
    source_sitegroups_preflight = _results["sitegroups"]
    source_sg_id_to_name = {sg.get("id"): sg.get("name") for sg in source_sitegroups_preflight}

    site_plan_ids = [sp.get("source_site_id") for sp in site_plans if sp.get("source_site_id")]
    site_details_map: dict = {}
    if site_plan_ids:
        with ThreadPoolExecutor(max_workers=min(len(site_plan_ids), 10)) as _ex:
            _fut_map = {
                _ex.submit(get_site_details, session, sid, source_base_url): sid
                for sid in site_plan_ids
            }
            for _future in as_completed(_fut_map):
                site_details_map[_fut_map[_future]] = _future.result()

    per_site_sitegroups = []
    for site_plan in site_plans:
        sp_site_id = site_plan.get("source_site_id")
        if not sp_site_id:
            continue
        sp_details = site_details_map.get(sp_site_id) or {}
        sg_ids = sp_details.get("sitegroup_ids") or []
        sg_names = [source_sg_id_to_name.get(sg_id, sg_id) for sg_id in sg_ids]
        per_site_sitegroups.append({
            "source_site_id": sp_site_id,
            "source_site_name": site_plan.get("source_site_name") or sp_site_id,
            "sitegroup_names": sg_names
        })

    mode4_expected_template_warnings = []
    if template_assignment_mode == "4":
        source_id_to_name, _, _ = build_template_maps(
            session, source_org_id, source_org_id,
            source_base_url=source_base_url, dest_base_url=source_base_url
        )
        wlan_site_map, wlan_org_level_ids = build_wlan_scope_info(
            session, source_org_id, base_url=source_base_url
        )
        for site_plan in site_plans:
            source_plan_site_id = site_plan.get("source_site_id")
            if not source_plan_site_id:
                continue
            source_site_details = site_details_map.get(source_plan_site_id) or \
                get_site_details(session, source_plan_site_id, base_url=source_base_url)
            source_template_ids = derive_source_site_template_ids(
                source_site_details,
                site_id=source_plan_site_id,
                wlan_site_map=wlan_site_map,
                wlan_org_level_ids=wlan_org_level_ids,
            )
            resolved_template_ids = resolve_template_ids_from_source(
                source_site_details,
                source_id_to_name,
                {},
                site_id=source_plan_site_id,
                wlan_site_map=wlan_site_map,
                wlan_org_level_ids=wlan_org_level_ids,
            )
            skip_reasons = compute_mode4_skip_reasons(
                source_template_ids,
                resolved_template_ids,
                source_id_to_name
            )
            mode4_expected_template_warnings.append({
                "source_site_id": source_plan_site_id,
                "source_site_name": site_plan.get("source_site_name") or source_plan_site_id,
                "skipped_templates": skip_reasons,
                "warning_summary": format_template_skip_warnings(skip_reasons)
            })

    return {
        "source_org_id": source_org_id,
        "source_site_id": source_site_id,
        "site_settings": site_settings,
        "site_settings_keys": settings_keys,
        "site_vars_count": vars_count,
        "templates": templates,
        "service_policies": service_policies,
        "template_selection_overrides": {
            "switch_template_id": template_name_map.get("switch_template_id"),
            "wan_edge_template_id": template_name_map.get("wan_edge_template_id"),
            "wlan_template_id": template_name_map.get("wlan_template_id"),
            "rftemplate_id": template_name_map.get("rftemplate_id")
        },
        "mode4_expected_template_warnings": mode4_expected_template_warnings,
        "sitegroups": [
            {"id": sg.get("id"), "name": sg.get("name")}
            for sg in source_sitegroups_preflight
        ],
        "per_site_sitegroup_assignments": per_site_sitegroups
    }


def preflight_summary(preflight_report, template_assignment_mode=""):
    ui.section("Preflight Summary")
    ui.bullet("Source org",  preflight_report['source_org_id'])
    ui.bullet("Source site", preflight_report['source_site_id'])

    settings_keys    = preflight_report.get("site_settings_keys", [])
    settings_preview = ", ".join(settings_keys[:10])
    settings_suffix  = "" if len(settings_keys) <= 10 else f" … (+{len(settings_keys) - 10} more)"
    ui.bullet("Site settings keys", settings_preview + settings_suffix)
    ui.bullet("Site variables", f"{preflight_report.get('site_vars_count', 0)} var(s)")

    print()
    for label, items in preflight_report.get("templates", {}).items():
        summarize_list(items, label.replace("_", " "))

    summarize_list(preflight_report.get("service_policies", []), "Service policies")
    summarize_list(preflight_report.get("sitegroups", []), "Site groups")

    per_site_sg = preflight_report.get("per_site_sitegroup_assignments", [])
    if per_site_sg:
        print()
        ui.bullet("Site group memberships (source)")
        for entry in per_site_sg:
            sg_names = ", ".join(entry.get("sitegroup_names") or []) or "<none>"
            ui.info(f"  {entry['source_site_name']}: {sg_names}")

    mode_label = {
        "1": "Clone all templates; select assignments per site",
        "2": "Clone all templates; one template per type for all sites",
        "3": "Clone a single template per type; apply to all sites",
        "4": "Match each site to its current templates",
    }.get(template_assignment_mode, "Not selected")
    print()
    ui.bullet("Template assignment mode", mode_label)


def build_preflight_markdown(report: dict, template_assignment_mode: str = "") -> str:
    lines = []

    def h1(t):  lines.extend([f"# {t}", ""])
    def h2(t):  lines.extend([f"## {t}", ""])
    def h3(t):  lines.extend([f"### {t}", ""])
    def row(*cols): lines.append("| " + " | ".join(str(c) for c in cols) + " |")
    def sep(*cols): lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    def blank():    lines.append("")

    h1("Mist Org Clone — Preflight Report")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    blank()
    lines.append("---")
    blank()

    h2("Organisation Overview")
    row("Field", "Value")
    sep("Field", "Value")
    row("Source org ID",  report.get("source_org_id",  "n/a"))
    row("Source site ID", report.get("source_site_id", "n/a"))
    blank()

    h2("Site Settings")
    settings_keys = report.get("site_settings_keys", [])
    vars_count    = report.get("site_vars_count", 0)
    row("Property", "Value")
    sep("Property", "Value")
    row("Setting keys found", len(settings_keys))
    row("Site variables",      f"{vars_count} var(s)")
    if settings_keys:
        preview = ", ".join(settings_keys[:15])
        if len(settings_keys) > 15:
            preview += f" … (+{len(settings_keys) - 15} more)"
        row("Keys (preview)", preview)
    blank()

    h2("Templates")
    label_map = {
        "switch_templates":   "Switch Templates",
        "wan_edge_templates": "WAN Edge Templates",
        "wlan_templates":     "WLAN Templates",
        "rf_templates":       "RF Templates",
    }
    for key, heading in label_map.items():
        items = report.get("templates", {}).get(key, [])
        h3(heading)
        if items:
            row("#", "Name", "ID")
            sep("#", "Name", "ID")
            for idx, item in enumerate(items, 1):
                row(idx, item.get("name", "(unnamed)"), item.get("id", ""))
        else:
            lines.append("*None found.*")
        blank()

    overrides = report.get("template_selection_overrides", {})
    if any(overrides.values()):
        h3("Config.ini Template Overrides")
        row("Template Type", "Override Name")
        sep("Template Type", "Override Name")
        label_overrides = {
            "switch_template_id":  "Switch",
            "wan_edge_template_id": "WAN Edge",
            "wlan_template_id":    "WLAN",
            "rftemplate_id":       "RF",
        }
        for k, lbl in label_overrides.items():
            val = overrides.get(k)
            if val:
                row(lbl, val)
        blank()

    h2("Service Policies")
    policies = report.get("service_policies", [])
    if policies:
        row("#", "Name", "ID")
        sep("#", "Name", "ID")
        for idx, p in enumerate(policies, 1):
            row(idx, p.get("name", "(unnamed)"), p.get("id", ""))
    else:
        lines.append("*None found.*")
    blank()

    h2("Site Groups")
    sitegroups = report.get("sitegroups", [])
    if sitegroups:
        row("#", "Name", "ID")
        sep("#", "Name", "ID")
        for idx, sg in enumerate(sitegroups, 1):
            row(idx, sg.get("name", "(unnamed)"), sg.get("id", ""))
    else:
        lines.append("*None found.*")
    blank()

    per_site_sg = report.get("per_site_sitegroup_assignments", [])
    if per_site_sg:
        h2("Site Group Memberships (per source site)")
        row("Source Site", "Site Groups")
        sep("Source Site", "Site Groups")
        for entry in per_site_sg:
            sg_names = ", ".join(entry.get("sitegroup_names") or []) or "*(none)*"
            row(entry.get("source_site_name", entry.get("source_site_id", "?")), sg_names)
        blank()

    h2("Template Assignment Mode")
    mode_label = {
        "1": "Mode 1 — Clone all templates; select assignments per site",
        "2": "Mode 2 — Clone all templates; one template per type for all sites",
        "3": "Mode 3 — Clone a single template per type; apply to all sites",
        "4": "Mode 4 — Match each site to its current source templates",
    }.get(template_assignment_mode, f"Unknown ({template_assignment_mode or 'not set'})")
    lines.append(f"> **{mode_label}**")
    blank()

    warnings = [
        w for w in report.get("mode4_expected_template_warnings", [])
        if w.get("skipped_templates")
    ]
    if warnings:
        h2("⚠️ Mode 4 Template Warnings")
        lines.append(
            "> The following source template assignments could not be automatically "
            "resolved to a matching template in the new org.  "
            "Review these before proceeding."
        )
        blank()
        for w in warnings:
            h3(f"Site: {w.get('source_site_name', w.get('source_site_id', '?'))}")
            summary = w.get("warning_summary", "")
            if summary:
                lines.append(summary)
            skipped = w.get("skipped_templates", {})
            if skipped:
                row("Template Type", "Reason")
                sep("Template Type", "Reason")
                for ttype, reason in skipped.items():
                    row(ttype.replace("_", " "), reason)
            blank()

    return "\n".join(lines) + "\n"
