import argparse
import json
import sys

import ui
from config import RunConfig, load_config, validate_config_vars, init_config_wizard, init_config_from_env
from session import build_session
from preflight import build_preflight_report, preflight_summary, build_preflight_markdown
from workflow import run_clone_flow, _setup_dest_context, _offer_save_log
from guided import guided_flow


def main():
    parser = argparse.ArgumentParser(description="Clone Mist orgs with optional preflight/dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Only perform preflight checks and exit.")
    parser.add_argument("--init", action="store_true", help="Run the config init wizard and exit.")
    parser.add_argument("--init-from-env", action="store_true", help="Create config.ini from environment variables and exit.")
    parser.add_argument("--preflight-json", nargs="?", const="preflight_report.json", help="Write preflight report to a JSON file.")
    parser.add_argument("--preflight", nargs="?", const="preflight_report.md", help="Write preflight report to a Markdown file (default: preflight_report.md).")
    parser.add_argument("--guided", action="store_true", help="Run the guided setup flow.")
    args = parser.parse_args()

    try:
        if len(sys.argv) == 1:
            args.guided = True

        if args.init:
            init_config_wizard()
            return

        if args.init_from_env:
            init_config_from_env()
            return

        if args.guided:
            guided_flow(args)
            return

        ui.start_log()
        selected_section_name, config_dict = load_config()
        cfg = RunConfig.from_dict(config_dict)

        source_headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {cfg.api_token}'
        }
        validate_config_vars(cfg)
        source_base_url = cfg.base_url
        source_session = build_session(extra_headers=source_headers)

        dest_session, dest_base_url, cross_cloud = _setup_dest_context(source_session, source_base_url)

        from guided import collect_run_details
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

        if args.preflight_json or args.preflight:
            out_path = args.preflight_json or args.preflight
            if out_path.endswith(".md") or args.preflight:
                md_content = build_preflight_markdown(preflight_report,
                                                      template_assignment_mode=cfg.template_assignment_mode)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
            else:
                with open(out_path, "w", encoding="utf-8") as file:
                    json.dump(preflight_report, file, indent=2, sort_keys=True)
            ui.ok(f"Preflight report written to {out_path}")

        if args.dry_run:
            ui.info("Dry-run mode — no changes applied.")
            _offer_save_log()
            return

        run_clone_flow(source_session, dest_session, source_base_url, dest_base_url,
                       template_name_map, cfg=cfg, cross_cloud=cross_cloud)
        _offer_save_log()

    except Exception as e:
        ui.error(str(e))


if __name__ == "__main__":
    main()
