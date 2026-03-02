import ui
from session import api_request, _paginate
from mist import _ORG_RESOURCE_STRIP_FIELDS


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


def clone_organization(session, source_org_id, new_org_name, source_base_url):
    url = f'{source_base_url}/orgs/{source_org_id}/clone'
    payload = {'name': new_org_name}
    response = api_request(session, "POST", url, payload=payload)
    return response.json()['id']


def invite_super_users(session, org_id, user_details, base_url):
    url = f'{base_url}/orgs/{org_id}/invites'
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


def fetch_alarm_templates(session, org_id, base_url):
    url = f'{base_url}/orgs/{org_id}/alarmtemplates'
    return _paginate(session, url)


def clone_alarm_templates(source_session, dest_session, source_org_id, new_org_id,
                          source_base_url, dest_base_url):
    ui.progress("Copying alarm templates …")
    source_templates = fetch_alarm_templates(source_session, source_org_id, base_url=source_base_url)
    if not source_templates:
        ui.info("No alarm templates found in source org.")
        return 0

    existing_templates = fetch_alarm_templates(dest_session, new_org_id, base_url=dest_base_url)
    existing_names = {t.get("name") for t in existing_templates if t.get("name")}

    create_url = f'{dest_base_url}/orgs/{new_org_id}/alarmtemplates'
    ok = 0
    already = 0
    for template in source_templates:
        name = template.get("name")
        if name in existing_names:
            already += 1
            continue
        payload = {k: v for k, v in template.items() if k not in _ORG_RESOURCE_STRIP_FIELDS}
        try:
            api_request(dest_session, "POST", create_url, payload=payload, ok_status=(200, 201))
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
