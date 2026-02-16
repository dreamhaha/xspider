#!/usr/bin/env python3
"""
Twitter Token 提取指南和验证工具

使用方法:
1. 在浏览器中登录 Twitter (https://twitter.com)
2. 打开开发者工具 (F12 或 Cmd+Option+I)
3. 切换到 Network 标签
4. 刷新页面或点击任意内容
5. 在请求列表中找到任意 "graphql" 请求
6. 点击请求，在 Headers 标签中找到以下信息:

=== 需要提取的信息 ===

1. authorization (Request Headers):
   Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D...
   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   复制 "Bearer " 后面的整个字符串

2. x-csrf-token (Request Headers):
   abc123def456ghi789...
   ^^^^^^^^^^^^^^^^^^^^
   复制整个值

3. cookie (Request Headers) 中的 auth_token:
   找到 auth_token=xxxxx; 部分，复制 xxxxx 值

=== 示例配置 ===

编辑 .env 文件，添加:

TWITTER_TOKENS='[
  {
    "bearer_token": "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
    "ct0": "your_ct0_value_here",
    "auth_token": "your_auth_token_value_here"
  }
]'

运行此脚本验证配置:
  python scripts/get_twitter_tokens.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv


def print_extraction_guide():
    """打印详细的 Token 提取指南"""
    guide = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                     Twitter Token 提取指南                                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  步骤 1: 登录 Twitter                                                         ║
║  ─────────────────────                                                       ║
║  打开 https://twitter.com 并登录你的账号                                      ║
║                                                                              ║
║  步骤 2: 打开开发者工具                                                        ║
║  ─────────────────────                                                       ║
║  • Mac: Cmd + Option + I                                                     ║
║  • Windows/Linux: F12 或 Ctrl + Shift + I                                    ║
║                                                                              ║
║  步骤 3: 切换到 Network 标签                                                   ║
║  ─────────────────────                                                       ║
║  点击顶部的 "Network" 标签                                                    ║
║                                                                              ║
║  步骤 4: 筛选 GraphQL 请求                                                     ║
║  ─────────────────────                                                       ║
║  在 Filter 输入框中输入: graphql                                              ║
║                                                                              ║
║  步骤 5: 触发请求                                                             ║
║  ─────────────────────                                                       ║
║  刷新页面 或 点击任意推文/用户                                                 ║
║                                                                              ║
║  步骤 6: 提取 Token                                                           ║
║  ─────────────────────                                                       ║
║  点击任意 graphql 请求 → Headers 标签 → Request Headers                       ║
║                                                                              ║
║  需要复制的三个值:                                                            ║
║                                                                              ║
║  ┌────────────────┬─────────────────────────────────────────────────────┐    ║
║  │ Header 名称     │ 说明                                                │    ║
║  ├────────────────┼─────────────────────────────────────────────────────┤    ║
║  │ authorization  │ 复制 "Bearer " 后面的整个字符串                       │    ║
║  │                │ (以 AAAAAAA... 开头的长字符串)                        │    ║
║  ├────────────────┼─────────────────────────────────────────────────────┤    ║
║  │ x-csrf-token   │ 复制整个值 (32-64 位字符串)                           │    ║
║  ├────────────────┼─────────────────────────────────────────────────────┤    ║
║  │ cookie         │ 在 cookie 值中找到 auth_token=xxx;                   │    ║
║  │                │ 只复制 xxx 部分 (= 和 ; 之间的值)                     │    ║
║  └────────────────┴─────────────────────────────────────────────────────┘    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    print(guide)


def validate_env_file():
    """验证 .env 文件配置"""
    env_path = Path(__file__).parent.parent / ".env"

    if not env_path.exists():
        print("\n❌ .env 文件不存在!")
        print(f"   请复制 .env.example 为 .env:")
        print(f"   cp .env.example .env")
        return None

    load_dotenv(env_path)

    tokens_str = os.getenv("TWITTER_TOKENS", "[]")

    try:
        tokens = json.loads(tokens_str)
    except json.JSONDecodeError as e:
        print(f"\n❌ TWITTER_TOKENS JSON 格式错误: {e}")
        return None

    if not tokens:
        print("\n❌ TWITTER_TOKENS 为空!")
        print("   请按照上述指南添加 Token")
        return None

    print(f"\n✅ 找到 {len(tokens)} 个 Token 配置")

    valid_tokens = []
    for i, token in enumerate(tokens):
        print(f"\n   Token #{i+1}:")

        bearer = token.get("bearer_token", "")
        ct0 = token.get("ct0", "")
        auth = token.get("auth_token", "")

        issues = []

        if not bearer:
            issues.append("bearer_token 缺失")
        elif not bearer.startswith("AAAAAAA"):
            issues.append("bearer_token 格式可能不正确 (应以 AAAAAAA 开头)")
        else:
            print(f"   • bearer_token: {bearer[:30]}... ✓")

        if not ct0:
            issues.append("ct0 缺失")
        elif len(ct0) < 20:
            issues.append(f"ct0 长度可能不正确 (当前: {len(ct0)}, 预期: 32-64)")
        else:
            print(f"   • ct0: {ct0[:20]}... ✓")

        if not auth:
            issues.append("auth_token 缺失")
        elif len(auth) < 20:
            issues.append(f"auth_token 长度可能不正确 (当前: {len(auth)})")
        else:
            print(f"   • auth_token: {auth[:20]}... ✓")

        if issues:
            for issue in issues:
                print(f"   ⚠️  {issue}")
        else:
            valid_tokens.append(token)

    return valid_tokens


async def test_twitter_connection(tokens: list):
    """测试 Twitter API 连接"""
    print("\n" + "=" * 60)
    print("测试 Twitter API 连接...")
    print("=" * 60)

    try:
        from xspider.core.config import TwitterToken
        from xspider.twitter.auth import TokenPool
        from xspider.twitter.proxy_pool import ProxyPool
        from xspider.twitter.client import TwitterGraphQLClient

        # 创建 Token 对象
        token_objects = [
            TwitterToken(
                bearer_token=t["bearer_token"],
                ct0=t["ct0"],
                auth_token=t["auth_token"],
            )
            for t in tokens
        ]

        # 创建客户端
        token_pool = TokenPool.from_tokens(token_objects)
        proxy_pool = ProxyPool.from_urls([])  # 暂不使用代理

        client = TwitterGraphQLClient(
            token_pool=token_pool,
            proxy_pool=proxy_pool,
        )

        # 测试 1: 获取 Twitter 官方账号
        print("\n📡 测试 1: 获取用户信息 (@elonmusk)...")
        try:
            user = await client.get_user_by_screen_name("elonmusk")
            print(f"   ✅ 成功!")
            print(f"   • ID: {user.id}")
            print(f"   • 用户名: @{user.username}")
            print(f"   • 显示名: {user.display_name}")
            print(f"   • 粉丝数: {user.followers_count:,}")
            print(f"   • 关注数: {user.following_count:,}")
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            return False

        # 测试 2: 获取 Following 列表
        print(f"\n📡 测试 2: 获取关注列表 (前 5 个)...")
        try:
            count = 0
            async for following in client.iter_following(user.id, max_users=5):
                count += 1
                print(f"   {count}. @{following.username} ({following.followers_count:,} 粉丝)")
            print(f"   ✅ 成功获取 {count} 个关注用户")
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            return False

        # 测试 3: 获取推文
        print(f"\n📡 测试 3: 获取最近推文 (前 3 条)...")
        try:
            tweets, _ = await client.get_user_tweets(user.id, count=3)
            for i, tweet in enumerate(tweets[:3], 1):
                text_preview = tweet.text[:50] + "..." if len(tweet.text) > 50 else tweet.text
                print(f"   {i}. {text_preview}")
                print(f"      ❤️ {tweet.like_count:,}  🔁 {tweet.retweet_count:,}")
            print(f"   ✅ 成功获取 {len(tweets)} 条推文")
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            return False

        await client.close()

        print("\n" + "=" * 60)
        print("🎉 所有测试通过! Twitter 连接正常")
        print("=" * 60)

        # 显示统计
        stats = token_pool.get_stats()
        print(f"\nToken 池状态:")
        print(f"   • 总 Token: {stats['total_tokens']}")
        print(f"   • 可用: {stats['available_tokens']}")
        print(f"   • 请求数: {stats['total_requests']}")

        return True

    except ImportError as e:
        print(f"\n❌ 导入模块失败: {e}")
        print("   请确保已安装依赖: uv pip install -e .")
        return False
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "=" * 60)
    print("       xspider - Twitter Token 配置工具")
    print("=" * 60)

    # 打印指南
    print_extraction_guide()

    # 验证配置
    tokens = validate_env_file()

    if not tokens:
        print("\n" + "-" * 60)
        print("请按照上述指南配置 .env 文件后重新运行此脚本")
        print("-" * 60)
        sys.exit(1)

    # 询问是否测试
    print("\n" + "-" * 60)
    response = input("是否测试 Twitter API 连接? [Y/n]: ").strip().lower()

    if response in ("", "y", "yes"):
        asyncio.run(test_twitter_connection(tokens))
    else:
        print("\n跳过测试。配置看起来正确，可以开始使用 xspider。")


if __name__ == "__main__":
    main()
