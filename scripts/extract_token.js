// 在 Twitter 页面的浏览器控制台 (Console) 中运行此脚本
// 步骤: F12 → Console → 粘贴以下代码 → 回车

(function() {
    // 获取 cookies
    const cookies = document.cookie.split(';').reduce((acc, cookie) => {
        const [key, value] = cookie.trim().split('=');
        acc[key] = value;
        return acc;
    }, {});

    const ct0 = cookies['ct0'];
    const auth_token = cookies['auth_token'];

    // Bearer token (固定值，Twitter Web 客户端使用)
    const bearer_token = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA';

    if (!ct0 || !auth_token) {
        console.error('❌ 无法获取 Token，请确保已登录 Twitter');
        return;
    }

    const config = {
        bearer_token: bearer_token,
        ct0: ct0,
        auth_token: auth_token
    };

    // 输出配置
    console.log('\n✅ Token 提取成功!\n');
    console.log('='.repeat(60));
    console.log('复制以下内容到 .env 文件:');
    console.log('='.repeat(60));
    console.log(`
TWITTER_TOKENS='[${JSON.stringify(config, null, 2)}]'
`);
    console.log('='.repeat(60));

    // 复制到剪贴板
    const envContent = `TWITTER_TOKENS='[${JSON.stringify(config)}]'`;
    navigator.clipboard.writeText(envContent).then(() => {
        console.log('\n📋 已复制到剪贴板! 直接粘贴到 .env 文件即可。');
    }).catch(() => {
        console.log('\n⚠️ 无法自动复制，请手动复制上面的内容。');
    });

    return config;
})();
