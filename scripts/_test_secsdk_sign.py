from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"
PATH = "/novelsale/distributor/content/series/list/v1/"


def test():
    with SeriesListClient(headless=True) as client:
        ctx = client._request_context()
        base_params = {
            "query": TARGET,
            "search_type": "2",
            "content_genre": "2",
            "sort_type": "1",
            "sort_field": "8",
            "aweme_user_new_version": "true",
            "page_index": "0",
            "page_size": "20",
        }

        def run(mode):
            return client.page.evaluate(
                """async ({ apiPath, params, mode }) => {
                    const qs = new URLSearchParams(params).toString();
                    const url = `${apiPath}?${qs}`;
                    let init = {};
                    if (mode === 'cred') init = { credentials: 'include' };
                    if (mode === 'none') init = {};
                    const res = await fetch(url, init);
                    const finalUrl = res.url;
                    const text = await res.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch (e) {}
                    const inner = json?.data || {};
                    const rows = inner.data || [];
                    return {
                        mode,
                        hasMsToken: finalUrl.includes('msToken'),
                        hasBogus: finalUrl.includes('a_bogus'),
                        total: inner.total,
                        count: rows.length,
                        first: rows[0]?.series_name || null,
                        urlTail: finalUrl.slice(-80),
                    };
                }""",
                {"apiPath": PATH, "params": {k: str(v) for k, v in base_params.items()}, "mode": mode},
            )

        for mode in ["none", "cred"]:
            print(run(mode))


if __name__ == "__main__":
    playwright_worker.run(test)
