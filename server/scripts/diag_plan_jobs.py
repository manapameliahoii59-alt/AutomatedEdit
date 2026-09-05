# -*- coding: utf-8 -*-
"""诊断策划任务：打印最近任务的完整错误与用户通道配置（在服务器上运行）。

用法（在 server/ 目录，用项目 venv 的 python）：
    python scripts/diag_plan_jobs.py              # 最近 10 条任务
    python scripts/diag_plan_jobs.py 关键词        # 按剧目/错误搜索，如剧目名片段
"""

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymysql

SERVER_ROOT = Path(__file__).resolve().parents[1]


def _load_database_url() -> str:
    text = (SERVER_ROOT / ".env").read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("DATABASE_URL="):
            return line.partition("=")[2].strip()
    raise SystemExit("server/.env 未找到 DATABASE_URL")


def _parse_db_url(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
    }


def main() -> None:
    keyword = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    conn = pymysql.connect(**_parse_db_url(_load_database_url()))
    try:
        with conn.cursor() as cur:
            sql = (
                "SELECT j.id, j.user_id, u.username, j.status, j.plan_mode, "
                "j.project_name, j.error, j.created_at, j.updated_at "
                "FROM plan_jobs j LEFT JOIN users u ON u.id = j.user_id "
            )
            params: tuple = ()
            if keyword:
                sql += "WHERE j.project_name LIKE %s OR j.error LIKE %s "
                like = f"%{keyword}%"
                params = (like, like)
            sql += "ORDER BY j.updated_at DESC LIMIT 10"
            cur.execute(sql, params)
            rows = cur.fetchall()

            print(f"=== 最近策划任务（{len(rows)} 条，完整真实错误）===")
            for r in rows:
                print("-" * 72)
                print(
                    f"[{r['updated_at']}] 任务 {r['id'][:12]}… "
                    f"用户: {r['username']} 状态: {r['status']} 模式: {r['plan_mode']}"
                )
                print(f"剧目: {r['project_name']}")
                print(f"错误: {(r['error'] or '').strip() or '(空)'}")

            print()
            print("=== 用户通道配置（Key 仅显示前 4 位用于辨认类型）===")
            cur.execute(
                "SELECT s.user_id, u.username, s.plan_llm_provider, s.plan_llm_model, "
                "LENGTH(s.deepseek_keys) AS key_len, LEFT(s.deepseek_keys, 4) AS key_head "
                "FROM user_secrets s LEFT JOIN users u ON u.id = s.user_id "
                "ORDER BY s.user_id"
            )
            for r in cur.fetchall():
                print(
                    f"{r['username']} (id={r['user_id']})  "
                    f"通道={r['plan_llm_provider']}  "
                    f"模型={r['plan_llm_model'] or '(通道默认)'}  "
                    f"Key={r['key_head']}…({r['key_len']} 位)"
                )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
