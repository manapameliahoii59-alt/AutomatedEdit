#!/usr/bin/env python3
"""创建业务用户（桌面端登录账号）。"""

import argparse
import getpass
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import User, UserSecret


def main():
    parser = argparse.ArgumentParser(description="创建 AutomatedEdit 用户")
    parser.add_argument("username")
    parser.add_argument("--role", choices=["user", "admin"], default="user")
    parser.add_argument("--deepseek-keys", default="", help="逗号分隔的 DeepSeek Key（策划）")
    parser.add_argument("--dashscope-key", default="")
    parser.add_argument("--valid-until", default="", help="使用期限 YYYY-MM-DD，留空=永久")
    args = parser.parse_args()

    password = getpass.getpass("密码: ")
    if len(password) < 6:
        print("密码至少 6 位")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        exists = db.scalar(select(User).where(User.username == args.username))
        if exists:
            print(f"用户 {args.username} 已存在")
            sys.exit(1)

        user = User(
            username=args.username,
            password_hash=hash_password(password),
            plain_password=password,
            role=args.role,
            is_active=True,
            valid_until=date.fromisoformat(args.valid_until) if args.valid_until else None,
        )
        db.add(user)
        db.flush()

        if args.deepseek_keys or args.dashscope_key:
            db.add(
                UserSecret(
                    user_id=user.id,
                    deepseek_keys=args.deepseek_keys,
                    dashscope_key=args.dashscope_key,
                )
            )

        db.commit()
        print(f"已创建用户: {args.username} (id={user.id}, role={args.role})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
