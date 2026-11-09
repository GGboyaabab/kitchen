# 家庭厨房 Android

第一版是 Android WebView 客户端，复用 Python 后端的选食材、菜谱推荐、跟做、照片上传和问答页面。小程序专属的模型管理和 AI 新菜谱生成页面尚未迁入 Android。

用 Android Studio 打开本目录，安装 Android SDK 35，同步 Gradle，然后选择 Build APK。工程需要 JDK 17 或 21 和 Gradle 8.9；未包含 Gradle wrapper。当前开发机器未安装 SDK，尚未编译或真机验证。

启动后端：设置 KITCHEN_PASSWORD，然后运行 `python app.py --host 0.0.0.0`。手机与电脑连接同一家庭 Wi-Fi，在 App 中填写 `http://电脑局域网IP:8765`，认证用户名由应用固定为 kitchen，输入你设置的密码。安卓模拟器访问电脑使用 `http://10.0.2.2:8765`。

HTTP 仅供可信家庭网络开发；远程使用应配置 HTTPS 网关。应用保存服务地址，访问密码仅用于当前认证，不写入应用配置。不要直接把 Python 开发服务公开到互联网。
