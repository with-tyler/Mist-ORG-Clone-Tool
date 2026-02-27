import argparse
import configparser
import json
import os
import sys
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import ui
from instance_selector import select_section

CONFIG_PATH = "config.ini"
DEFAULT_TIMEOUT = (5, 30)

config_vars = {}
headers = {}


def prompt_input(label, default=None, allow_empty=False):
    return ui.ask(label, default=default, allow_empty=allow_empty)


def prompt_yes_no(label, default=True):
    return ui.ask_yn(label, default=default)


def parse_superuser_details(raw_details):
    users = []
    if not raw_details or not raw_details.strip():
        return users

    entries = [entry.strip() for entry in raw_details.split(',') if entry.strip()]
    for entry in entries:
        parts = [part.strip() for part in entry.split(':')]
        if len(parts) == 1:
            email = parts[0]
            if email:
                users.append({"email": email, "first_name": "", "last_name": ""})
            continue

        if len(parts) == 3:
            email, first_name, last_name = parts
            if not email:
                raise Exception(f"Invalid superuser detail: '{entry}'. Missing email.")
            users.append({"email": email, "first_name": first_name, "last_name": last_name})
            continue

        raise Exception(
            f"Invalid superuser detail: '{entry}'. Expected email or email:first:last."
        )

    return users


def format_superuser_details(users):
    return ",".join(
        f"{user['email']}:{user.get('first_name', '')}:{user.get('last_name', '')}"
        for user in users
    )


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


def manage_api_keys():
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)

    while True:
        sections = config.sections()
        ui.section("API Key Management")
        if sections:
            ui.info("Existing profiles:")
            for idx, sec in enumerate(sections, start=1):
                base_url = config[sec].get("base_url", "")
                ui.info(f"  {idx}.  {sec}  ({base_url})")
        else:
            ui.warn("No API key profiles found.")

        ui.menu("Choose an action", [
            ("1", "Add new API key"),
            ("2", "Update existing API key"),
            ("3", "Delete API key"),
            ("4", "Done"),
        ])
        choice = prompt_input("Select option", default="1")

        if choice == "4":
            break

        if choice == "1":
            section_name = prompt_input("New section name", default="LOCAL01")
            base_url = prompt_input("Base URL", default="https://api.mist.com/api/v1")
            api_token = prompt_input("API token (input visible)")
            while not api_token:
                ui.warn("API token required.")
                api_token = prompt_input("API token (input visible)")
            config[section_name] = {
                "api_token": api_token,
                "base_url": base_url
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                config.write(file)
            ui.ok(f"Profile '{section_name}' added.")
            continue

        if choice == "2":
            if not sections:
                ui.warn("No profiles to update.")
                continue
            selection = prompt_input("Section number to update", default="1")
            try:
                index = int(selection) - 1
                section_name = sections[index]
            except (ValueError, IndexError):
                ui.warn("Invalid selection.")
                continue
            base_url = prompt_input(
                "Base URL",
                default=config[section_name].get("base_url", "https://api.mist.com/api/v1")
            )
            api_token = prompt_input("API token (input visible)")
            while not api_token:
                ui.warn("API token required.")
                api_token = prompt_input("API token (input visible)")
            config[section_name]["base_url"] = base_url
            config[section_name]["api_token"] = api_token
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                config.write(file)
            ui.ok(f"Profile '{section_name}' updated.")
            continue

        if choice == "3":
            if not sections:
                ui.warn("No profiles to delete.")
                continue
            selection = prompt_input("Section number to delete", default="1")
            try:
                index = int(selection) - 1
                section_name = sections[index]
            except (ValueError, IndexError):
                ui.warn("Invalid selection.")
                continue
            if not prompt_yes_no(f"Delete profile '{section_name}'?", default=False):
                continue
            config.remove_section(section_name)
            with open(CONFIG_PATH, "w", encoding="utf-8") as file:
                config.write(file)
            ui.ok(f"Profile '{section_name}' deleted.")
            continue

        ui.warn("Invalid option.")


def select_from_list(items, item_label, name_key="name", id_key="id"):
    if not items:
        return None
    ui.section(f"Select {item_label.title()}")
    ui.numbered_list(items, name_key=name_key, id_key=id_key)
    selection = prompt_input("Enter number (or press Enter to skip)", default="", allow_empty=True)
    if not selection:
        return None
    try:
        index = int(selection) - 1
        if 0 <= index < len(items):
            return items[index].get(id_key)
    except ValueError:
        pass
    ui.warn("Invalid selection — skipping.")
    return None


def select_name_from_list(items, item_label, name_key="name", id_key="id"):
    if not items:
        return None
    ui.section(f"Select {item_label.title()}")
    ui.numbered_list(items, name_key=name_key, id_key=id_key)
    selection = prompt_input("Enter number (or press Enter to skip)", default="", allow_empty=True)
    if not selection:
        return None
    try:
        index = int(selection) - 1
        if 0 <= index < len(items):
            return items[index].get(name_key)
    except ValueError:
        pass
    ui.warn("Invalid selection — skipping.")
    return None


def try_list_orgs(session, base_url):
    endpoints = [
        f"{base_url}/self",
        f"{base_url}/orgs",
        f"{base_url}/self/orgs"
    ]

    last_error = None
    for url in endpoints:
        try:
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

                return response.json(), None

            last_error = (
                f"{url} returned status {response.status_code}: {response.text[:300]}"
            )
        except requests.RequestException as exc:
            last_error = f"{url} network/API error: {exc}"

    return None, last_error


def try_list_sites(session, base_url, org_id):
    # Prefer the org sites endpoint — it returns full objects (address, country_code, sitegroup_ids).
    # Fall back to /self which only returns site privilege stubs.
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

                return response.json(), None

            last_error = (
                f"{url} returned status {response.status_code}: {response.text[:300]}"
            )
        except requests.RequestException as exc:
            last_error = f"{url} network/API error: {exc}"

    return None, last_error


def get_site_details(session, site_id, base_url=None):
    url = f"{base_url or config_vars['base_url']}/sites/{site_id}"
    response = api_request(session, "GET", url)
    return response.json()


def fetch_templates(session, org_id, base_url=None):
    _base = base_url or config_vars['base_url']
    endpoints = {
        "switch": f"{_base}/orgs/{org_id}/networktemplates",
        "wan_edge": f"{_base}/orgs/{org_id}/gatewaytemplates",
        "wlan": f"{_base}/orgs/{org_id}/templates",
        "rf": f"{_base}/orgs/{org_id}/rftemplates"
    }
    templates = {}
    for key, url in endpoints.items():
        response = api_request(session, "GET", url)
        templates[key] = response.json()
    return templates


def build_template_maps(session, source_org_id, new_org_id,
                        source_base_url=None, dest_base_url=None, dest_session=None):
    _src_base = source_base_url or config_vars['base_url']
    _dst_base = dest_base_url   or config_vars['base_url']
    _dst_sess = dest_session    or session
    source_templates = fetch_templates(session,   source_org_id, base_url=_src_base)
    new_templates    = fetch_templates(_dst_sess, new_org_id,    base_url=_dst_base)

    source_id_to_name = {}
    for key, items in source_templates.items():
        source_id_to_name[key] = {item.get("id"): item.get("name") for item in items}

    new_name_to_id = {}
    for key, items in new_templates.items():
        new_name_to_id[key] = {item.get("name"): item.get("id") for item in items}

    return source_id_to_name, new_name_to_id, new_templates


def build_wlan_scope_info(session, org_id, base_url=None):
    """
    Fetch all WLAN templates for an org and categorise them by assignment scope.

    Returns:
        site_map (dict):       {site_id: [template_id, ...]}  – site-level assignments
        org_level_ids (set):   {template_id, ...}             – org-wide assignments
                                                                 (applies.org_id is set)
    """
    url = f'{base_url or config_vars["base_url"]}/orgs/{org_id}/templates'
    response = api_request(session, "GET", url)
    site_map: dict = {}
    org_level_ids: set = set()

    def _add_site(sid, tid):
        if sid and tid:
            site_map.setdefault(sid, [])
            if tid not in site_map[sid]:
                site_map[sid].append(tid)

    for template in response.json():
        template_id = template.get("id")
        if not template_id:
            continue
        applies = template.get("applies")
        if isinstance(applies, dict):
            # Org-wide assignment takes precedence over any site list
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


# Keep a thin alias so any external callers still work
def build_wlan_site_template_map(session, org_id, base_url=None):
    site_map, _ = build_wlan_scope_info(session, org_id, base_url=base_url)
    return site_map


def fetch_sitegroups(session, org_id, base_url=None):
    """Returns list of sitegroup objects {id, name} for an org."""
    url = f'{base_url or config_vars["base_url"]}/orgs/{org_id}/sitegroups'
    response = api_request(session, "GET", url)
    return response.json()


def build_sitegroup_name_to_id(sitegroups):
    return {sg.get("name"): sg.get("id") for sg in sitegroups if sg.get("name") and sg.get("id")}


def clone_sitegroup_membership(session, source_site_details, source_sitegroups,
                               new_sitegroup_name_to_id, new_org_id, new_site_id,
                               base_url=None):
    """
    Assigns the new site to the sitegroups that its source counterpart belongs to,
    matched by sitegroup name. Returns a list of sitegroup names that could not be matched.
    """
    source_sg_ids = source_site_details.get("sitegroup_ids") or []
    if not source_sg_ids:
        return []

    source_id_to_name = {sg.get("id"): sg.get("name") for sg in source_sitegroups}
    new_sg_ids = []
    unmatched = []

    for sg_id in source_sg_ids:
        name = source_id_to_name.get(sg_id)
        if not name:
            unmatched.append(sg_id)
            continue
        new_id = new_sitegroup_name_to_id.get(name)
        if new_id:
            new_sg_ids.append(new_id)
        else:
            unmatched.append(name)

    if new_sg_ids:
        url = f'{base_url or config_vars["base_url"]}/orgs/{new_org_id}/sites/{new_site_id}'
        api_request(session, "PUT", url, payload={"sitegroup_ids": new_sg_ids})

    return unmatched


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
    # wlan_org_template_id shares the same name lookup table as wlan_template_id
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
                continue  # omit entirely when no org-level WLAN assigned
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
        # wlan / wlan_org keys hold lists
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


def derive_source_site_template_ids(
    site_details,
    site_id=None,
    wlan_site_map=None,
    wlan_org_level_ids=None,
):
    """
    Build a dict of template IDs that apply to this source site.

    Keys:
        switch, wan_edge, rf  – single IDs (or None)
        wlan                  – list of site-level WLAN template IDs (or None)
        wlan_org              – list of org-level WLAN template IDs (or None)
                                These are already applied to the whole org and
                                must be assigned differently than site-level ones.
    """
    template_ids = {
        "switch":   site_details.get("networktemplate_id"),
        "wan_edge": site_details.get("gatewaytemplate_id"),
        "rf":       site_details.get("rftemplate_id"),
        "wlan":     [],
        "wlan_org": [],
    }

    # Site-level WLAN IDs embedded in site details
    for key in ["wlan_template_id", "template_id", "wlan_template"]:
        if site_details.get(key):
            template_ids["wlan"].append(site_details[key])
            break

    if isinstance(site_details.get("wlan_template_ids"), list) and site_details["wlan_template_ids"]:
        template_ids["wlan"].extend(site_details["wlan_template_ids"])

    if wlan_site_map and site_id:
        template_ids["wlan"].extend(wlan_site_map.get(site_id, []))

    # Org-level WLAN IDs apply to every site in the org
    if wlan_org_level_ids:
        template_ids["wlan_org"].extend(wlan_org_level_ids)

    template_ids["wlan"]     = template_ids["wlan"]     or None
    template_ids["wlan_org"] = template_ids["wlan_org"] or None

    return template_ids


def resolve_template_ids_from_source(
    site_details,
    source_maps,
    new_maps,
    site_id=None,
    wlan_site_map=None,
    wlan_org_level_ids=None,
):
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

        # Both wlan (site-level) and wlan_org (org-level) are resolved the same
        # way (name lookup), but kept in separate buckets so assignment can
        # use the correct applies scope.
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


def init_config_wizard():
    ui.section("API Key Config Wizard")
    manage_api_keys()


def init_config_from_env():
    section_name = os.getenv("MIST_CONFIG_SECTION", "ENV01")
    env_config = {
        "api_token": os.getenv("MIST_API_TOKEN", "").strip(),
        "base_url": os.getenv("MIST_BASE_URL", "https://api.mist.com/api/v1").strip()
    }

    missing = [key for key, value in env_config.items() if not value]
    if missing:
        raise Exception(f"Missing required env vars for: {', '.join(missing)}")

    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        config.read(CONFIG_PATH)
    config[section_name] = env_config

    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        config.write(file)

    ui.ok(f"Updated {CONFIG_PATH} with section '{section_name}' from environment variables.")


def _select_api_profile(select_title: str) -> tuple[str, dict]:
    """
    Show configured API profiles, optionally manage them, then prompt for
    selection.  Creates config.ini via manage_api_keys() if none exists yet.
    """
    # Ensure at least one profile exists before we attempt selection.
    if not os.path.exists(CONFIG_PATH):
        ui.warn("No API key profiles found. Please add one now.")
        manage_api_keys()

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if not config.sections():
        ui.warn("No API key profiles found. Please add one now.")
        manage_api_keys()

    # Show current profiles so the user knows what is already configured.
    config.read(CONFIG_PATH)
    sections = config.sections()
    ui.info("Configured profiles:")
    for idx, sec in enumerate(sections, start=1):
        base_url = config[sec].get("base_url", "")
        ui.info(f"  {idx}.  {sec}  ({base_url})")
    print()

    if prompt_yes_no("Add or manage API key profiles?", default=False):
        manage_api_keys()

    return select_section(CONFIG_PATH, title=select_title)


def load_config(init_requested=False):
    if init_requested or not os.path.exists(CONFIG_PATH):
        init_config_wizard()

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    return select_section(CONFIG_PATH)


def load_dest_config():
    """Select (or add) a destination cloud instance profile from config.ini."""
    return _select_api_profile("Select Destination Cloud Instance")


def persist_section_updates(section_name, updates):
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if section_name not in config:
        raise Exception(f"Section '{section_name}' not found in {CONFIG_PATH}.")

    for key, value in updates.items():
        config[section_name][key] = value

    with open(CONFIG_PATH, "w", encoding="utf-8") as file:
        config.write(file)


def build_session(extra_headers=None):
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(extra_headers or headers)
    return session


def api_request(session, method, url, payload=None, ok_status=(200,)):
    response = session.request(
        method,
        url,
        json=payload,
        timeout=DEFAULT_TIMEOUT
    )
    if response.status_code in ok_status:
        return response
    raise Exception(f"{method} {url} failed: {response.text}")


def validate_config_vars(vars_dict):
    required_keys = [
        "api_token",
        "base_url"
    ]
    missing = [key for key in required_keys if not vars_dict.get(key)]
    if missing:
        raise Exception(f"Missing required config values: {', '.join(missing)}")


def collect_run_details(session, base_url):
    ui.section("Step 2 — Source Configuration")
    orgs, org_error = try_list_orgs(session, base_url)
    if orgs is not None:
        config_vars["source_organization_id"] = select_from_list(orgs, "orgs")
    else:
        ui.warn(f"Unable to list orgs: {org_error}")

    if not config_vars.get("source_organization_id"):
        config_vars["source_organization_id"] = prompt_input("Source organization ID")

    sites, site_error = try_list_sites(session, base_url, config_vars["source_organization_id"])
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

    config_vars["source_site_id"] = selected_sites[0]["id"]
    config_vars["new_organization_name"] = prompt_input("New organization name")
    config_vars["new_superuser_details"] = collect_superusers_for_guided_flow("")

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

    config_vars["site_plans"] = site_plans
    config_vars["site_clone_mode"] = site_mode

    config_vars["template_assignment_mode"] = prompt_template_assignment_mode()


def clone_organization(session, source_org_id, new_org_name, source_base_url=None):
    """Same-cloud clone using the Mist /clone endpoint."""
    url = f'{source_base_url or config_vars["base_url"]}/orgs/{source_org_id}/clone'
    payload = {'name': new_org_name}
    response = api_request(session, "POST", url, payload=payload)
    return response.json()['id']


def create_site(session, org_id, site_name, site_address, country_code, base_url=None):
    url = f'{base_url or config_vars["base_url"]}/orgs/{org_id}/sites'
    payload = {'name': site_name, 'address': site_address, 'country_code': country_code}
    response = api_request(session, "POST", url, payload=payload)
    return response.json()['id']


def get_site_settings(session, site_id, base_url=None):
    url = f'{base_url or config_vars["base_url"]}/sites/{site_id}/setting'
    response = api_request(session, "GET", url)
    return response.json()


# Fields that are read-only, site-specific, or handled separately via explicit assignment.
_SITE_SETTINGS_STRIP_FIELDS = {
    "id", "org_id", "site_id", "for_site", "created_time", "modified_time",
    "networktemplate_id", "gatewaytemplate_id", "rftemplate_id", "alarmtemplate_id"
}


def copy_site_settings(session, source_site_id, target_site_id,
                       source_base_url=None, dest_base_url=None, dest_session=None):
    _src_base  = source_base_url or config_vars['base_url']
    _dst_base  = dest_base_url   or config_vars['base_url']
    _dst_sess  = dest_session    or session
    site_settings = get_site_settings(session, source_site_id, base_url=_src_base)
    # Strip read-only and template-assignment fields — template IDs from the source org
    # are invalid in the new org and are applied separately via assign_templates.
    cleaned = {k: v for k, v in site_settings.items() if k not in _SITE_SETTINGS_STRIP_FIELDS}
    url = f'{_dst_base}/sites/{target_site_id}/setting'
    api_request(_dst_sess, "PUT", url, payload=cleaned)


_SITE_WLAN_STRIP_FIELDS = {"id", "org_id", "site_id", "created_time", "modified_time"}


def fetch_site_wlans(session, site_id, base_url=None):
    """Return all site-specific WLANs for a site (may be empty list)."""
    url = f'{base_url or config_vars["base_url"]}/sites/{site_id}/wlans'
    try:
        response = api_request(session, "GET", url)
        return response.json()
    except Exception as exc:
        ui.warn(f"Could not fetch site WLANs for site {site_id}: {exc}")
        return []


def clone_site_wlans(source_session, dest_session, source_site_id, dest_site_id,
                     source_base_url=None, dest_base_url=None):
    """Copy site-specific WLANs from source site to destination site."""
    _src_base = source_base_url or config_vars['base_url']
    _dst_base = dest_base_url or config_vars['base_url']
    _dst_sess = dest_session or source_session
    wlans = fetch_site_wlans(source_session, source_site_id, base_url=_src_base)
    if not wlans:
        return 0
    create_url = f'{_dst_base}/sites/{dest_site_id}/wlans'
    ok = 0
    for wlan in wlans:
        payload = {k: v for k, v in wlan.items() if k not in _SITE_WLAN_STRIP_FIELDS}
        try:
            api_request(_dst_sess, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok += 1
        except Exception as exc:
            ui.warn(f"Site WLAN '{wlan.get('ssid', wlan.get('id'))}' skipped: {exc}")
    return ok


_SITE_MAP_STRIP_FIELDS = {"id", "org_id", "site_id", "created_time", "modified_time", "url", "thumbnail_url"}


def fetch_site_maps(session, site_id, base_url=None):
    """Return all floor plan maps for a site (may be empty list)."""
    url = f'{base_url or config_vars["base_url"]}/sites/{site_id}/maps'
    try:
        response = api_request(session, "GET", url)
        return response.json()
    except Exception as exc:
        ui.warn(f"Could not fetch site maps for site {site_id}: {exc}")
        return []


def clone_site_maps(source_session, dest_session, source_site_id, dest_site_id,
                    source_base_url=None, dest_base_url=None):
    """
    Copy floor plan maps from source site to destination site.

    For each map:
      1. Strip read-only fields and POST the metadata to create the map.
      2. If the source map has an image URL, download it and re-upload it
         as multipart form data to the new map's image endpoint.

    Returns the number of maps successfully created (image failures are
    warned but do not reduce the count).
    """
    _src_base = source_base_url or config_vars['base_url']
    _dst_base = dest_base_url or config_vars['base_url']
    _dst_sess = dest_session or source_session

    maps = fetch_site_maps(source_session, source_site_id, base_url=_src_base)
    if not maps:
        return 0

    create_url = f'{_dst_base}/sites/{dest_site_id}/maps'
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
            try:
                img_resp = requests.get(source_image_url, timeout=DEFAULT_TIMEOUT)
                if img_resp.status_code == 200:
                    image_bytes = img_resp.content
                    content_type = img_resp.headers.get("Content-Type", "application/octet-stream")
                    filename = source_image_url.split("/")[-1].split("?")[0] or "map_image"
                    upload_url = f'{_dst_base}/sites/{dest_site_id}/maps/{new_map_id}/image'
                    up_resp = _dst_sess.post(
                        upload_url,
                        files={'file': (filename, image_bytes, content_type)},
                        headers={'Content-Type': None},
                        timeout=DEFAULT_TIMEOUT,
                    )
                    if up_resp.status_code not in (200, 201):
                        ui.warn(f"Map image upload failed for '{site_map.get('name')}': {up_resp.text[:200]}")
                else:
                    ui.warn(f"Could not download map image for '{site_map.get('name')}': HTTP {img_resp.status_code}")
            except Exception as exc:
                ui.warn(f"Map image upload skipped for '{site_map.get('name')}': {exc}")

        ok += 1
    return ok


def assign_templates(session, org_id, site_id, template_ids, base_url=None):
    """
    Assign non-WLAN templates to a site (switch, wan-edge, rf).

    WLAN templates are intentionally excluded here because applies.site_ids is
    a complete list on the template object — not additive.  All sites must be
    collected first and then applied in a single PUT via finalize_wlan_assignments.
    """
    _base = base_url or config_vars['base_url']
    non_wlan = {
        "switch_template_id":   {"networktemplate_id": template_ids.get("switch_template_id")},
        "wan_edge_template_id": {"gatewaytemplate_id": template_ids.get("wan_edge_template_id")},
        "rftemplate_id":        {"rftemplate_id":       template_ids.get("rftemplate_id")},
    }
    for key, payload in non_wlan.items():
        if not template_ids.get(key):
            continue
        url = f'{_base}/sites/{site_id}'
        api_request(session, "PUT", url, payload=payload)
        ui.ok(f"{key.replace('_', ' ').title()} assigned.")


def finalize_wlan_assignments(
    session,
    new_org_id: str,
    site_level_map: dict,
    org_level_ids: set,
    id_name_map: dict,
    base_url: str = None,
) -> None:
    """
    Apply WLAN template assignments in a single PUT per template.

    site_level_map  – {new_wlan_template_id: [new_site_id, ...]}  accumulated
                      across all sites.  Written as applies.site_ids (complete
                      list — replaces whatever the cloned org carried over).
    org_level_ids   – {new_wlan_template_id, ...}  written as applies.org_id.
                      The clone copies the source org_id; this resets it to the
                      new org so the template actually applies to the new org.
    """
    if not site_level_map and not org_level_ids:
        return

    _base = base_url or config_vars['base_url']
    ui.section("WLAN Template Assignment")

    for wlan_id, new_site_ids in site_level_map.items():
        name = id_name_map.get("wlan_template_id", {}).get(wlan_id, wlan_id)
        url = f'{_base}/orgs/{new_org_id}/templates/{wlan_id}'
        payload = {"applies": {"site_ids": new_site_ids}}
        api_request(session, "PUT", url, payload=payload)
        ui.ok(f"WLAN (site-level) '{name}'  →  {len(new_site_ids)} site(s): {new_site_ids}")

    for wlan_id in org_level_ids:
        name = id_name_map.get("wlan_template_id", {}).get(wlan_id, wlan_id)
        url = f'{_base}/orgs/{new_org_id}/templates/{wlan_id}'
        payload = {"applies": {"org_id": new_org_id}}
        api_request(session, "PUT", url, payload=payload)
        ui.ok(f"WLAN (org-level)  '{name}'  →  applies to all sites in new org.")


def invite_super_users(session, org_id, user_details, base_url=None):
    url = f'{base_url or config_vars["base_url"]}/orgs/{org_id}/invites'
    for user in parse_superuser_details(user_details):
        email = user["email"]
        first_name = user.get("first_name", "")
        last_name = user.get("last_name", "")
        payload = {
            'email': email.strip(),
            'first_name': first_name.strip(),
            'last_name': last_name.strip(),
            'hours': 24,
            'privileges': [{'scope': 'org', 'role': 'admin'}]
        }
        api_request(session, "POST", url, payload=payload)


def summarize_list(items, label, max_items=5):
    ui.summarize_list(items, label, max_items=max_items)


def build_preflight_report(session, source_org_id, source_site_id, template_name_map,
                           source_base_url=None):
    _src_base = source_base_url or config_vars['base_url']
    site_settings = get_site_settings(session, source_site_id, base_url=_src_base)
    settings_keys = sorted(site_settings.keys())
    vars_count = len(site_settings.get("vars", {})) if isinstance(site_settings.get("vars"), dict) else 0

    template_endpoints = {
        "switch_templates":   f'{_src_base}/orgs/{source_org_id}/networktemplates',
        "wan_edge_templates": f'{_src_base}/orgs/{source_org_id}/gatewaytemplates',
        "wlan_templates":     f'{_src_base}/orgs/{source_org_id}/templates',
        "rf_templates":       f'{_src_base}/orgs/{source_org_id}/rftemplates'
    }

    templates = {}
    for label, url in template_endpoints.items():
        response = api_request(session, "GET", url)
        templates[label] = [
            {"id": item.get("id"), "name": item.get("name")}
            for item in response.json()
        ]

    response = api_request(session, "GET", f'{_src_base}/orgs/{source_org_id}/servicepolicies')
    service_policies = [
        {"id": item.get("id"), "name": item.get("name")}
        for item in response.json()
    ]

    source_sitegroups_preflight = fetch_sitegroups(session, source_org_id, base_url=_src_base)
    source_sg_id_to_name = {sg.get("id"): sg.get("name") for sg in source_sitegroups_preflight}
    per_site_sitegroups = []
    for site_plan in config_vars.get("site_plans", []):
        sp_site_id = site_plan.get("source_site_id")
        if not sp_site_id:
            continue
        sp_details = get_site_details(session, sp_site_id, base_url=_src_base)
        sg_ids = sp_details.get("sitegroup_ids") or []
        sg_names = [source_sg_id_to_name.get(sg_id, sg_id) for sg_id in sg_ids]
        per_site_sitegroups.append({
            "source_site_id": sp_site_id,
            "source_site_name": site_plan.get("source_site_name") or sp_site_id,
            "sitegroup_names": sg_names
        })

    mode4_expected_template_warnings = []
    if config_vars.get("template_assignment_mode") == "4":
        source_id_to_name, _, _ = build_template_maps(
            session, source_org_id, source_org_id,
            source_base_url=_src_base, dest_base_url=_src_base
        )
        wlan_site_map, wlan_org_level_ids = build_wlan_scope_info(
            session, source_org_id, base_url=_src_base
        )
        for site_plan in config_vars.get("site_plans", []):
            source_plan_site_id = site_plan.get("source_site_id")
            if not source_plan_site_id:
                continue
            source_site_details = get_site_details(session, source_plan_site_id, base_url=_src_base)
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


def preflight_summary(preflight_report):
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

    assignment_mode = config_vars.get("template_assignment_mode", "")
    mode_label = {
        "1": "Clone all templates; select assignments per site",
        "2": "Clone all templates; one template per type for all sites",
        "3": "Clone a single template per type; apply to all sites",
        "4": "Match each site to its current templates",
    }.get(assignment_mode, "Not selected")
    print()
    ui.bullet("Template assignment mode", mode_label)


_SERVICEPOLICY_STRIP_FIELDS = {"id", "org_id", "created_time", "modified_time"}


def remap_gateway_template_service_policies(session, source_org_id, new_org_id,
                                            source_base_url=None, dest_base_url=None,
                                            dest_session=None):
    """
    Ensure service policies exist in the new org and re-apply them to every
    gateway template so path_preference bindings are correct.

    When Mist's server-side /clone runs it copies service policies to the new
    org under NEW IDs and also rewrites the servicepolicy_id references inside
    the cloned gateway templates.  This means:
      - The gateway templates already reference the new-org IDs, not source IDs.
      - We must build old_id → new_id via name-matching against the already-
        cloned policies rather than by POSTing duplicates.
      - Any source policy that was NOT cloned (edge-case) is created on-demand.

    Steps:
      1. Read source org policies  → source_id_to_name
      2. Read new org policies     → new_name_to_id   (Mist already cloned these)
      3. For any policy missing by name, create it and add to new_name_to_id.
      4. Build source_id → new_id via name.
      5. Read every gateway template from the new org; rebuild its
         service_policies list using the new IDs (preserving path_preference).
    """
    _src_base = source_base_url or config_vars['base_url']
    _dst_base = dest_base_url   or config_vars['base_url']
    _dst_sess = dest_session    or session

    source_policies = api_request(
        session, "GET", f'{_src_base}/orgs/{source_org_id}/servicepolicies'
    ).json()

    # Build lookup: source_id → name
    source_id_to_name = {}
    source_name_to_action = {}
    for policy in source_policies:
        pid  = policy.get("id")
        name = policy.get("name")
        if pid and name:
            source_id_to_name[pid] = name
            source_name_to_action[name] = policy.get("action", "allow")

    # Build lookup: name → id  from the policies already in the new org
    # (Mist's server-side clone copies them with new IDs).
    new_policies = api_request(
        _dst_sess, "GET", f'{_dst_base}/orgs/{new_org_id}/servicepolicies'
    ).json()
    new_name_to_id = {}
    new_id_to_action = {}
    for policy in new_policies:
        pid  = policy.get("id")
        name = policy.get("name")
        if pid and name:
            new_name_to_id[name] = pid
            new_id_to_action[pid] = policy.get("action", "allow")

    # Create any source policy that was not cloned (should be rare).
    create_url = f'{_dst_base}/orgs/{new_org_id}/servicepolicies'
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

    # Build source_id → new_id via name.
    source_id_to_new_id = {
        src_id: new_name_to_id[name]
        for src_id, name in source_id_to_name.items()
        if name in new_name_to_id
    }
    if source_policies:
        ui.ok(f"Service policy ID map built: {len(source_id_to_new_id)}/{len(source_id_to_name)} resolved.")

    # Patch each gateway template to restore all service policies correctly.
    #
    # There are two kinds of entries in a gateway template's service_policies list:
    #
    #   1. Referenced  — {"servicepolicy_id": "<uuid>", "path_preference": "..."}
    #      These reference an org-level service policy object.  The source template
    #      always holds source-org IDs, which we translate via source_id_to_new_id.
    #
    #   2. Inline  — {"name": "...", "tenants": [...], "services": [...], "action": "..."}
    #      These are self-contained rules embedded directly in the template.
    #      Mist's /clone strips them completely, leaving service_policies: [].
    #      We restore them from the source template verbatim.
    #
    # Strategy: use the source template as the authoritative list, rebuild from scratch.

    source_gateway_templates = api_request(
        session, "GET", f'{_src_base}/orgs/{source_org_id}/gatewaytemplates'
    ).json()
    source_gw_by_name = {t.get("name"): t for t in source_gateway_templates if t.get("name")}

    gateway_templates = api_request(
        _dst_sess, "GET", f'{_dst_base}/orgs/{new_org_id}/gatewaytemplates'
    ).json()

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
                # Referenced policy — source template always holds source-org IDs.
                # Translate to the new-org ID via the name map built above.
                resolved_id = source_id_to_new_id.get(src_id)
                if resolved_id:
                    new_svc_policies.append({
                        "servicepolicy_id": resolved_id,
                        "path_preference": entry.get("path_preference", "WAN1")
                    })
                else:
                    skipped.append(src_id)
            else:
                # Inline policy — no org-level ID; copy the full entry verbatim.
                # Mist's /clone drops these; we restore them from the source template.
                new_svc_policies.append(entry)

        # Sort: deny/block policies first, then allow.
        # Inline entries use their own "action" field; referenced ones use new_id_to_action.
        new_svc_policies.sort(key=_policy_sort_key)

        gw_url = f'{_dst_base}/orgs/{new_org_id}/gatewaytemplates/{gw_id}'
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


# ── Cross-cloud org bootstrap ──────────────────────────────────────────────────

_ORG_RESOURCE_STRIP_FIELDS = {"id", "org_id", "created_time", "modified_time"}


def fetch_alarm_templates(session, org_id, base_url=None):
    """Return all alarm templates for an org."""
    url = f'{base_url or config_vars["base_url"]}/orgs/{org_id}/alarmtemplates'
    response = api_request(session, "GET", url)
    return response.json()


def clone_alarm_templates(source_session, dest_session, source_org_id, new_org_id,
                          source_base_url=None, dest_base_url=None):
    """
    Ensure all source org alarm templates exist in the destination org.

    For same-cloud clones the Mist server-side /clone already copies alarm
    templates, so we skip any template whose name is already present and only
    create those that are genuinely missing.  This makes the function safe to
    call in both same-cloud and cross-cloud scenarios without creating duplicates.

    Returns the number of alarm templates created (already-present ones are not
    counted but are not an error).
    """
    _src_base = source_base_url or config_vars['base_url']
    _dst_base = dest_base_url or config_vars['base_url']
    _dst_sess = dest_session or source_session

    ui.progress("Copying alarm templates …")
    source_templates = fetch_alarm_templates(source_session, source_org_id, base_url=_src_base)
    if not source_templates:
        ui.info("No alarm templates found in source org.")
        return 0

    # Find which names already exist in the destination org (e.g. from Mist /clone).
    existing_templates = fetch_alarm_templates(_dst_sess, new_org_id, base_url=_dst_base)
    existing_names = {t.get("name") for t in existing_templates if t.get("name")}

    create_url = f'{_dst_base}/orgs/{new_org_id}/alarmtemplates'
    ok = 0
    already = 0
    for template in source_templates:
        name = template.get("name")
        if name in existing_names:
            already += 1
            continue
        payload = {k: v for k, v in template.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            api_request(_dst_sess, "POST", create_url, payload=payload, ok_status=(200, 201))
            ok += 1
        except Exception as exc:
            ui.warn(f"Alarm template '{name}' skipped: {exc}")

    if already:
        ui.info(f"Alarm templates already present (skipped): {already}/{len(source_templates)}")
    if ok:
        ui.ok(f"Alarm templates created: {ok}/{len(source_templates)}")
    if not ok and not already:
        ui.info("No alarm templates to copy.")
    return ok


def cross_cloud_bootstrap_org(source_session, dest_session, source_org_id,
                               new_org_name, source_base_url, dest_base_url):
    """
    For cross-cloud cloning: create a blank org on the destination cloud and
    manually copy all org-level resources so the site-creation loop can proceed
    identically to the same-cloud path.

    Copies in order:
      1. Blank org creation
      2. Sitegroups
      3. Service policies
      4. Switch templates (networktemplates)
      5. RF templates
      6. WLAN templates
      7. WAN Edge / gateway templates  ← service policy IDs remapped inline
      8. Alarm templates

    Returns: new_org_id (str)
    """
    ui.progress("Creating blank organization on destination cloud …")
    org_url = f"{dest_base_url}/orgs"
    response = api_request(dest_session, "POST", org_url,
                           payload={"name": new_org_name}, ok_status=(200, 201))
    new_org_id = response.json()["id"]
    ui.ok(f"Blank organization created  →  ID: {new_org_id}")

    # 1. Sitegroups
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

    # 2. Service policies — copy first so gateway templates can reference them
    ui.progress("Copying service policies …")
    sp_src_url = f"{source_base_url}/orgs/{source_org_id}/servicepolicies"
    source_policies = api_request(source_session, "GET", sp_src_url).json()
    sp_id_map: dict = {}   # old_id → new_id
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

    # 3-6. Template types (order matters: gatewaytemplates last so sp_id_map is full)
    template_copy_tasks = [
        ("Switch",    "networktemplates"),
        ("RF",        "rftemplates"),
        ("WLAN",      "templates"),
        ("WAN Edge",  "gatewaytemplates"),
    ]
    for label, endpoint in template_copy_tasks:
        ui.progress(f"Copying {label} templates …")
        items = api_request(
            source_session, "GET", f"{source_base_url}/orgs/{source_org_id}/{endpoint}"
        ).json()
        create_url = f"{dest_base_url}/orgs/{new_org_id}/{endpoint}"
        t_ok = 0
        for item in items:
            payload = {k: v for k, v in item.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
            # Remap service policy IDs inside gateway templates.
            # Only entries with a servicepolicy_id are referenced policies and
            # need remapping.  Inline entries (no servicepolicy_id) are copied verbatim.
            if endpoint == "gatewaytemplates":
                old_svc = payload.get("service_policies") or []
                remapped = []
                for entry in old_svc:
                    src_sp_id = entry.get("servicepolicy_id")
                    if src_sp_id:
                        remapped.append({
                            **entry,
                            "servicepolicy_id": sp_id_map.get(src_sp_id, src_sp_id)
                        })
                    else:
                        # Inline policy — copy as-is (no ID to remap)
                        remapped.append(entry)
                payload["service_policies"] = remapped
            try:
                api_request(dest_session, "POST", create_url,
                            payload=payload, ok_status=(200, 201))
                t_ok += 1
            except Exception as exc:
                ui.warn(f"{label} template '{item.get('name')}' skipped: {exc}")
        ui.ok(f"{label} templates copied: {t_ok}/{len(items)}")

    # 8. Alarm templates
    clone_alarm_templates(
        source_session, dest_session, source_org_id, new_org_id,
        source_base_url=source_base_url, dest_base_url=dest_base_url,
    )

    return new_org_id


# ── NAC / Access Assurance cloning ─────────────────────────────────────────────

def _remap_ids_recursive(obj, id_map):
    """
    Recursively walk a nested dict/list and replace any string value that is a
    key in id_map with the corresponding new ID.
    """
    if isinstance(obj, dict):
        return {k: _remap_ids_recursive(v, id_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remap_ids_recursive(item, id_map) for item in obj]
    if isinstance(obj, str) and obj in id_map:
        return id_map[obj]
    return obj


def clone_nac_sso_roles(source_session, dest_session, source_org_id, dest_org_id,
                        source_base_url=None, dest_base_url=None):
    """Clone org SSO Role definitions. Returns {source_id: dest_id} map."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        items = api_request(source_session, "GET", f"{_src}/orgs/{source_org_id}/ssoroles").json()
    except Exception as exc:
        ui.warn(f"Could not fetch SSO roles: {exc}")
        return {}
    if not items:
        ui.info("No SSO roles found in source org.")
        return {}
    create_url = f"{_dst}/orgs/{dest_org_id}/ssoroles"
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
                   ssorole_id_map, source_base_url=None, dest_base_url=None):
    """Clone SSO configurations with ssorole_id remapping. Returns {source_sso_id: dest_sso_id} map."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        items = api_request(source_session, "GET", f"{_src}/orgs/{source_org_id}/ssos").json()
    except Exception as exc:
        ui.warn(f"Could not fetch SSOs: {exc}")
        return {}
    if not items:
        ui.info("No SSOs found in source org.")
        return {}
    create_url = f"{_dst}/orgs/{dest_org_id}/ssos"
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
                       source_base_url=None, dest_base_url=None):
    """Copy the mist_nac block from source org settings to the destination org."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        source_settings = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/setting"
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
            dest_session, "PUT", f"{_dst}/orgs/{dest_org_id}/setting",
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
                   source_base_url=None, dest_base_url=None):
    """Copy SCEP configuration. The CA certificate is org-specific and will be regenerated."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        scep = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/setting/mist_scep"
        ).json()
    except Exception:
        ui.info("SCEP settings not found or not accessible — skipping.")
        return
    if not scep.get("enabled"):
        ui.info("SCEP is not enabled in source org — skipping.")
        return
    try:
        api_request(
            dest_session, "PUT", f"{_dst}/orgs/{dest_org_id}/setting/mist_scep",
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
                   source_base_url=None, dest_base_url=None):
    """Clone NAC Tags. Returns {source_tag_id: dest_tag_id} map."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        items = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/nactags"
        ).json()
    except Exception as exc:
        ui.warn(f"Could not fetch NAC tags: {exc}")
        return {}
    if not items:
        ui.info("No NAC tags found in source org.")
        return {}
    create_url = f"{_dst}/orgs/{dest_org_id}/nactags"
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
                    nactag_id_map, source_base_url=None, dest_base_url=None):
    """Clone NAC Rules, remapping all embedded nactag_id references."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        items = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/nacrules"
        ).json()
    except Exception as exc:
        ui.warn(f"Could not fetch NAC rules: {exc}")
        return
    if not items:
        ui.info("No NAC rules found in source org.")
        return
    create_url = f"{_dst}/orgs/{dest_org_id}/nacrules"
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
                      nactag_id_map, sso_id_map, source_base_url=None, dest_base_url=None):
    """Clone NAC Portals, remapping nactag_id and sso_id references."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        items = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/nacportals"
        ).json()
    except Exception as exc:
        ui.warn(f"Could not fetch NAC portals: {exc}")
        return
    if not items:
        ui.info("No NAC portals found in source org.")
        return
    create_url = f"{_dst}/orgs/{dest_org_id}/nacportals"
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
                      source_base_url=None, dest_base_url=None):
    """
    Clone PSK Portals from /orgs/{id}/pskportals.

    The 'ui_url' field is org-specific and auto-generated — it is stripped
    before POST along with the standard read-only fields.  The 'sso' block
    and any image URL fields are copied as-is; manual post-clone steps are
    emitted for items that cannot be transferred automatically.
    """
    _PSK_EXTRA_STRIP = {"ui_url"}
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    try:
        items = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/pskportals"
        ).json()
    except Exception as exc:
        ui.warn(f"Could not fetch PSK portals: {exc}")
        return
    if not items:
        ui.info("No PSK portals found in source org.")
        return
    create_url = f"{_dst}/orgs/{dest_org_id}/pskportals"
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
    """Emit a manual-action notice for CRL files (binary uploads — cannot be cloned via API)."""
    ui.warn("ACTION REQUIRED — Certificate Revocation Lists (CRLs):")
    ui.info("  CRL files are uploaded binary files and cannot be transferred automatically.")
    ui.info("  If the source org has CRLs configured, re-upload them to the destination org:")
    ui.info("    Mist UI → Organization → Access → Access Assurance → Certificates → Upload CRL")


def clone_user_macs(source_session, dest_session, source_org_id, dest_org_id,
                    source_base_url=None, dest_base_url=None):
    """Optionally clone User MAC entries (endpoint identities with labels)."""
    _src = source_base_url or config_vars['base_url']
    _dst = dest_base_url or config_vars['base_url']
    if not prompt_yes_no("Clone User MAC entries (endpoint identities with labels)?", default=False):
        ui.info("User MAC entries skipped.")
        return
    try:
        items = api_request(
            source_session, "GET", f"{_src}/orgs/{source_org_id}/usermacs"
        ).json()
    except Exception as exc:
        ui.warn(f"Could not fetch User MACs: {exc}")
        return
    if not items:
        ui.info("No User MAC entries found in source org.")
        return
    create_url = f"{_dst}/orgs/{dest_org_id}/usermacs"
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
              source_base_url=None, dest_base_url=None):
    """
    Orchestrates full NAC / Access Assurance cloning in dependency order:

      1. Org NAC settings  (mist_nac block from org settings)
      2. SCEP configuration
      3. SSO Roles          (no dependencies)
      4. SSOs               (references SSO Roles)
      5. NAC Tags           (no dependencies)
      6. NAC Rules          (references NAC Tags)
      7. NAC Portals        (references NAC Tags + SSOs)
      8. PSK Portals        (no ID dependencies; org-specific ui_url stripped)
      9. CRL notice         (manual action — binary files cannot be cloned)
     10. User MACs          (optional, prompted — endpoint identities)

    Items that CANNOT be cloned automatically (user is notified inline):
      - SAML SP metadata (unique per org — must re-register with IdP)
      - SSO / IDP Allowable Domains (not in /ssos payload)
      - CRL files (binary uploads)
      - NAC Portal branding images (binary uploads)
      - PSK Portal branding images (binary uploads)
      - PSK Portal SSO SP metadata (unique per org)
      - SCEP CA certificate (regenerated per org)
      - RADIUS shared secrets / IDP credentials (copied but must be verified)
    """
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


# ── Main clone orchestration ────────────────────────────────────────────────────

def run_clone_flow(source_session, dest_session, source_base_url, dest_base_url,
                   template_name_map, cross_cloud=False):
    """
    Orchestrates the full clone.  When cross_cloud=True the destination is a
    different Mist cloud endpoint; otherwise the fast server-side /clone is used.
    """
    ui.section("Step 4 — Cloning Organization")

    if cross_cloud:
        ui.progress("Bootstrapping organization on destination cloud …")
        new_org_id = cross_cloud_bootstrap_org(
            source_session, dest_session,
            config_vars["source_organization_id"],
            config_vars["new_organization_name"],
            source_base_url, dest_base_url,
        )
        ui.ok(f"Organization bootstrapped on destination  →  ID: {new_org_id}")
        # Service policies and gateway templates were already handled inside
        # cross_cloud_bootstrap_org — skip the same-cloud remap step.
    else:
        ui.progress("Cloning organization structure …")
        new_org_id = clone_organization(
            source_session,
            config_vars["source_organization_id"],
            config_vars["new_organization_name"],
            source_base_url=source_base_url,
        )
        ui.ok(f"Organization cloned  →  ID: {new_org_id}")
        remap_gateway_template_service_policies(
            source_session, config_vars["source_organization_id"], new_org_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
            dest_session=dest_session,
        )
        ui.section("Alarm Templates")
        clone_alarm_templates(
            source_session, dest_session,
            config_vars["source_organization_id"], new_org_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
        )

    ui.section("Access Assurance (NAC)")
    if ui.ask_yn("Clone Access Assurance (NAC) configuration?", default=True):
        clone_nac(
            source_session, dest_session,
            config_vars["source_organization_id"], new_org_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
        )
    else:
        ui.info("NAC cloning skipped.")

    source_maps, new_maps, new_templates = build_template_maps(
        source_session,
        config_vars["source_organization_id"],
        new_org_id,
        source_base_url=source_base_url,
        dest_base_url=dest_base_url,
        dest_session=dest_session,
    )
    new_id_name_map = build_new_template_id_map(new_templates)

    # Build alarm template name maps for per-site remapping.
    # alarmtemplate_id is ORG-level (like switch/rf/gateway) but assigned per-site;
    # source IDs are stripped from site settings and re-applied by name here.
    source_alarm_templates = fetch_alarm_templates(
        source_session, config_vars["source_organization_id"], base_url=source_base_url
    )
    new_alarm_templates = fetch_alarm_templates(dest_session, new_org_id, base_url=dest_base_url)
    source_alarm_id_to_name = {t.get("id"): t.get("name") for t in source_alarm_templates if t.get("id")}
    new_alarm_name_to_id = {t.get("name"): t.get("id") for t in new_alarm_templates if t.get("name")}

    # Learn the WLAN scope of every cloned/bootstrapped template in the new org so that
    # user selections in modes 1/2/3 are routed to the right bucket.
    _, new_org_wlan_org_ids = build_wlan_scope_info(dest_session, new_org_id, base_url=dest_base_url)

    source_sitegroups = fetch_sitegroups(
        source_session, config_vars["source_organization_id"], base_url=source_base_url
    )
    new_sitegroups = fetch_sitegroups(dest_session, new_org_id, base_url=dest_base_url)
    new_sitegroup_name_to_id = build_sitegroup_name_to_id(new_sitegroups)
    if source_sitegroups:
        ui.info(f"Site groups: {len(source_sitegroups)} in source, {len(new_sitegroups)} in new org.")

    assignment_mode = config_vars.get("template_assignment_mode", "2")
    global_template_ids = {}
    per_site_apply_all = False
    per_site_template_ids = {}
    wlan_site_map = {}
    wlan_org_level_ids: set = set()
    # Accumulators populated during the site loop; applied once after via finalize_wlan_assignments.
    site_level_wlan_map: dict = {}
    org_level_wlan_ids_new: set = set()
    if assignment_mode == "4":
        wlan_site_map, wlan_org_level_ids = build_wlan_scope_info(
            source_session, config_vars["source_organization_id"], base_url=source_base_url
        )

    if assignment_mode in {"2", "3"}:
        ui.section("Template Selection (applies to all sites)")
        name_choices = prompt_template_choices_for_org(new_templates)
        for key, name in name_choices.items():
            new_id = new_maps.get(key, {}).get(name)
            if not new_id:
                continue
            # If the user picks a WLAN template that is org-scoped in the new
            # org (mirrors the source), put it in wlan_org so finalize applies
            # it with applies.org_id rather than applies.site_ids.
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

    for site_plan in config_vars.get("site_plans", []):
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
        )
        ui.ok("Site settings copied.")

        ui.progress("Copying site-specific WLANs …")
        wlan_count = clone_site_wlans(
            source_session, dest_session,
            site_plan["source_site_id"], new_site_id,
            source_base_url=source_base_url, dest_base_url=dest_base_url,
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
        )
        if maps_count:
            ui.ok(f"Site maps copied: {maps_count}")
        else:
            ui.info("No site maps found.")

        source_site_details_for_sg = get_site_details(
            source_session, site_plan["source_site_id"], base_url=source_base_url
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

        # Remap and apply alarmtemplate_id (always auto-mapped by name, independent of mode)
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

        # Separate WLAN from non-WLAN before assigning
        site_wlan = template_ids.pop("wlan_template_id", None)
        org_wlan  = template_ids.pop("wlan_org_template_id", None)

        # Accumulate site-level WLAN assignments
        if site_wlan:
            for tid in (site_wlan if isinstance(site_wlan, list) else [site_wlan]):
                site_level_wlan_map.setdefault(tid, []).append(new_site_id)

        # Accumulate org-level WLAN assignments (one PUT per template, not per site)
        if org_wlan:
            for tid in (org_wlan if isinstance(org_wlan, list) else [org_wlan]):
                org_level_wlan_ids_new.add(tid)

        if not any(template_ids.values()):
            ui.info("No non-WLAN templates selected for assignment.")
        else:
            ui.progress("Assigning non-WLAN templates …")
            assign_templates(dest_session, new_org_id, new_site_id, template_ids,
                             base_url=dest_base_url)

        # Summary line for this site (include WLAN even though it's deferred)
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

    # Apply all WLAN assignments now that every site_id is known
    finalize_wlan_assignments(
        dest_session,
        new_org_id,
        site_level_wlan_map,
        org_level_wlan_ids_new,
        new_id_name_map,
        base_url=dest_base_url,
    )

    if config_vars["new_superuser_details"]:
        ui.progress("Inviting super users …")
        invite_super_users(dest_session, new_org_id, config_vars["new_superuser_details"],
                           base_url=dest_base_url)
        ui.ok("Super users invited to new organization.")
    else:
        ui.info("No super users invited — none selected for this run.")


def _setup_dest_context(source_session, source_base_url):
    """
    Interactively decide whether to clone to the same cloud instance or a
    different one.  Returns (dest_session, dest_base_url, cross_cloud).
    """
    ui.section("Step 1b — Destination Instance")
    ui.menu("Clone Mode", [
        ("1", "Same cloud instance (default)"),
        ("2", "Different cloud instance (cross-cloud)"),
    ])
    mode = prompt_input("Select option", default="1")

    if mode == "2":
        dest_section_name, dest_vars = load_dest_config()
        validate_config_vars(dest_vars)
        dest_headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {dest_vars["api_token"]}'
        }
        dest_session = build_session(extra_headers=dest_headers)
        dest_base_url = dest_vars["base_url"]
        ui.ok(f"Destination: {dest_section_name}  ({dest_base_url})")
        return dest_session, dest_base_url, True

    dest_base_url = source_base_url
    return source_session, dest_base_url, False


def _write_run_log(path: str) -> None:
    """Write the captured UI log buffer to a Markdown file."""
    lines = ui.get_log_lines()
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Mist Org Clone — Run Log\n\n")
        f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
        f.write("---\n\n")
        for line in lines:
            f.write(line + "\n")
    ui.ok(f"Run log saved to {path}")


def _offer_save_log() -> None:
    """Ask the user if they want to save the full run log to a Markdown file."""
    if ui.ask_yn("Save a full run log to a Markdown file?", default=True):
        log_path = ui.ask("Log filename", default="clone_log.md")
        _write_run_log(log_path)


def guided_flow(args):
    ui.start_log()
    ui.banner("Mist Org Clone Tool", "Guided Setup")
    ui.section("Step 1 — Source API Configuration")

    selected_section_name, config_vars_local = _select_api_profile("Select Cloud Instance")

    global config_vars
    global headers
    config_vars = config_vars_local
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Token {config_vars["api_token"]}'
    }

    validate_config_vars(config_vars)
    source_base_url = config_vars["base_url"]
    source_session = build_session()

    dest_session, dest_base_url, cross_cloud = _setup_dest_context(source_session, source_base_url)

    collect_run_details(source_session, source_base_url)

    template_name_map = {
        "switch_template_id": config_vars.get("switch_template_name"),
        "wan_edge_template_id": config_vars.get("wan_edge_template_name"),
        "wlan_template_id": config_vars.get("wlan_template_name"),
        "rftemplate_id": config_vars.get("rf_template_name")
    }

    preflight_report = build_preflight_report(
        source_session, config_vars["source_organization_id"],
        config_vars["source_site_id"], template_name_map,
        source_base_url=source_base_url,
    )
    preflight_summary(preflight_report)

    if cross_cloud:
        ui.bullet("Clone mode", f"Cross-cloud  →  {dest_base_url}")
    else:
        ui.bullet("Clone mode", "Same cloud instance")

    ui.section("Step 3 — Preflight Options")
    report_path = args.preflight_json
    if report_path is None:
        write_report = prompt_yes_no("Write preflight report to JSON?", default=True)
        if write_report:
            report_path = prompt_input("Report filename", default="preflight_report.json")
    if report_path:
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
                   template_name_map, cross_cloud=cross_cloud)
    _offer_save_log()


def main():
    parser = argparse.ArgumentParser(description="Clone Mist orgs with optional preflight/dry-run.")
    parser.add_argument("--dry-run", action="store_true", help="Only perform preflight checks and exit.")
    parser.add_argument("--init", action="store_true", help="Run the config init wizard and exit.")
    parser.add_argument("--init-from-env", action="store_true", help="Create config.ini from environment variables and exit.")
    parser.add_argument("--preflight-json", nargs="?", const="preflight_report.json", help="Write preflight report to JSON file.")
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

        global config_vars
        global headers
        ui.start_log()
        selected_section_name, config_vars = load_config()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {config_vars["api_token"]}'
        }

        validate_config_vars(config_vars)
        source_base_url = config_vars["base_url"]
        source_session = build_session()

        dest_session, dest_base_url, cross_cloud = _setup_dest_context(source_session, source_base_url)

        collect_run_details(source_session, source_base_url)

        template_name_map = {
            "switch_template_id": config_vars.get("switch_template_name"),
            "wan_edge_template_id": config_vars.get("wan_edge_template_name"),
            "wlan_template_id": config_vars.get("wlan_template_name"),
            "rftemplate_id": config_vars.get("rf_template_name")
        }

        preflight_report = build_preflight_report(
            source_session, config_vars["source_organization_id"],
            config_vars["source_site_id"], template_name_map,
            source_base_url=source_base_url,
        )
        preflight_summary(preflight_report)
        if args.preflight_json:
            with open(args.preflight_json, "w", encoding="utf-8") as file:
                json.dump(preflight_report, file, indent=2, sort_keys=True)
            ui.ok(f"Preflight report written to {args.preflight_json}")
        if args.dry_run:
            ui.info("Dry-run mode — no changes applied.")
            _offer_save_log()
            return

        run_clone_flow(source_session, dest_session, source_base_url, dest_base_url,
                       template_name_map, cross_cloud=cross_cloud)
        _offer_save_log()

    except Exception as e:
        ui.error(str(e))

if __name__ == "__main__":
    main()