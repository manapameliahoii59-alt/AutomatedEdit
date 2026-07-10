from app.core.playwright_worker import playwright_worker
from app.data.services.series_list_client import SeriesListClient

TARGET = "爱意迟暮不相逢"
PATH = "/novelsale/distributor/content/series/list/v1/"


def test():
    with SeriesListClient(headless=True) as client:
        ctx = client._request_context()
        params = {
            "query": TARGET,
            "search_type": "2",
            "content_genre": "2",
            "sort_type": "1",
            "sort_field": "8",
            "aweme_user_new_version": "true",
            "page_index": "0",
            "page_size": "20",
        }

        def run(header_mode):
            return client.page.evaluate(
                """async ({ apiPath, params, app, adUserId, rootAdUserId, headerMode }) => {
                    const qs = new URLSearchParams(params).toString();
                    const url = `${apiPath}?${qs}`;
                    let headers = { accept: 'application/json, text/plain, */*' };
                    if (headerMode === 'app') {
                        headers.appid = String(app.app_id);
                        headers.apptype = String(app.app_type);
                        headers.distributorid = String(app.distributor_id);
                        headers.aduserid = adUserId;
                        headers['agw-js-conv'] = 'str';
                    }
                    if (headerMode === 'app_root') {
                        headers.appid = String(app.app_id);
                        headers.apptype = String(app.app_type);
                        headers.distributorid = String(app.distributor_id);
                        headers.aduserid = adUserId;
                        headers.rootaduserid = rootAdUserId;
                        headers['agw-js-conv'] = 'str';
                    }
                    if (headerMode === 'current') {
                        headers = {
                            accept: 'application/json, text/plain, */*',
                            appid: String(app.app_id),
                            apptype: String(app.app_type),
                            distributorid: String(app.distributor_id),
                            aduserid: adUserId,
                            'agw-js-conv': 'str',
                            'x-secsdk-csrf-token': 'DOWNGRADE',
                            referer: 'https://www.changdupingtai.com/sale/short-play/list',
                        };
                    }
                    const res = await fetch(url, { credentials: 'include', headers });
                    const text = await res.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch (e) {}
                    const inner = json?.data || {};
                    const rows = inner.data || [];
                    return {
                        headerMode,
                        code: json?.code,
                        msg: json?.message,
                        hasMsToken: res.url.includes('msToken'),
                        total: inner.total,
                        count: rows.length,
                        first: rows[0]?.series_name || null,
                    };
                }""",
                {
                    "apiPath": PATH,
                    "params": {k: str(v) for k, v in params.items()},
                    "headerMode": header_mode,
                    **ctx,
                },
            )

        for mode in ["app", "app_root", "current"]:
            print(run(mode))


if __name__ == "__main__":
    playwright_worker.run(test)
