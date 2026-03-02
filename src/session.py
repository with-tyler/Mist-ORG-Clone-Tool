import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = (5, 30)


def build_session(extra_headers=None, pool_size=20):
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE"]
    )
    adapter = HTTPAdapter(
        max_retries=retries,
        pool_connections=pool_size,
        pool_maxsize=pool_size,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if extra_headers:
        session.headers.update(extra_headers)
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


def _paginate(session, url):
    results = []
    page = 1
    limit = 1000
    sep = "&" if "?" in url else "?"
    while True:
        paged = f"{url}{sep}page={page}&limit={limit}"
        data = api_request(session, "GET", paged).json()
        if not isinstance(data, list):
            return data
        results.extend(data)
        if len(data) < limit:
            break
        page += 1
    return results
