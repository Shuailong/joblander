"""数据库迁移（Cloud Run 作业，每次发布前跑一次）：以表所有者身份建表 / 加策略，并建好应用角色。

  JOBLANDER_DB_HOST=… JOBLANDER_DB_USER=engine_owner JOBLANDER_DB_PASSWORD=… \
  JOBLANDER_APP_DB_PASSWORD=… python -m joblander.cloud.migrate_db
"""

from __future__ import annotations

import os


def main() -> None:
    from joblander.cloud.backend import dsn_from_parts
    from joblander.storage.pg import migrate
    dsn = os.environ.get("JOBLANDER_DB_DSN", "") or dsn_from_parts()
    if not dsn:
        raise SystemExit("缺数据库连接（JOBLANDER_DB_DSN 或 JOBLANDER_DB_HOST 等）")
    n = migrate(dsn, app_role=os.environ.get("JOBLANDER_APP_DB_ROLE", "engine_app"),
                app_password=os.environ.get("JOBLANDER_APP_DB_PASSWORD") or None)
    print(f"migrations applied: {n}")


if __name__ == "__main__":
    main()
