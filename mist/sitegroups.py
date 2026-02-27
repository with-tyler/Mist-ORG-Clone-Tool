import ui
from session import api_request, _paginate


def fetch_sitegroups(session, org_id, base_url):
    url = f'{base_url}/orgs/{org_id}/sitegroups'
    return _paginate(session, url)


def build_sitegroup_name_to_id(sitegroups):
    return {sg.get("name"): sg.get("id") for sg in sitegroups if sg.get("name") and sg.get("id")}


def clone_sitegroup_membership(session, source_site_details, source_sitegroups,
                               new_sitegroup_name_to_id, new_org_id, new_site_id,
                               base_url):
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
        url = f'{base_url}/orgs/{new_org_id}/sites/{new_site_id}'
        api_request(session, "PUT", url, payload={"sitegroup_ids": new_sg_ids})

    return unmatched
