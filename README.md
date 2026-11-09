# 厨房小程序

当前方案只做微信小程序，不再依赖 Kindle。`miniprogram/pages/home/` 是给家人使用的做饭首页：选食材、设置人数与时间、看推荐、逐步做饭和向助手提问；`miniprogram/pages/manage/` 是管理员入口：拍照识别、食材/菜谱管理、食材图生成和模型 Token 配置。

服务端使用两枚独立口令：

```powershell
$env:KITCHEN_APP_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))")
$env:KITCHEN_ADMIN_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))")
$env:KITCHEN_SECRET_KEY = (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python app.py
```

首页填写服务地址和 `KITCHEN_APP_TOKEN`；点击“管理厨房”后填写同一服务地址和 `KITCHEN_ADMIN_TOKEN`。两枚口令均只保留在当次小程序内存，模型厂商 Token 只保存于服务端加密数据库，不进入小程序源码。开发者工具本机可使用 `http://127.0.0.1:8765`；真机和发布环境必须使用 HTTPS，并在微信后台配置 request、uploadFile、downloadFile 合法域名。

### 菜谱生成与数据导入

首页的“AI 生成菜谱”会先从本地菜谱库按已选食材、时间筛出 3 道参考菜谱，再调用 CHAT 模型返回严格 JSON。结果默认是“待确认”，只有点击保存才会写入家庭菜谱库。模型没有配置时，此功能会明确提示，不影响手工菜谱与本地推荐。

确认授权和字段质量后的 JSON 数据可用导入工具写入数据库：

```powershell
python tools/import_recipe_json.py C:\path\to\reviewed-recipes.json --limit 100
```

JSON 应为菜谱数组，或包含 `recipes` 数组的对象；每项需要 `name`、`minutes`、`servings`、`ingredients`、`amounts`、`steps`。导入器会跳过格式不合格的数据。不要将来源与授权不明的抓取内容直接导入或重新发布。

已提供 howtocook 的专用导入器。使用前再次确认上游许可证，再对解压后的源码执行：

```powershell
python tools/import_howtocook.py C:\path\to\HowToCook-master --limit 100
```

导入时只保留菜名、食材、用量与步骤文本，图片和 Markdown 源文件不会写入应用；数据库会记录来源版本。默认人数和时长是用于推荐的保守初始值，用户可以在管理页修订。

## Kindle 动画设计预览

以下动画文件是早期设计资产，当前小程序不使用，可保留作参考或后续删除。

运行 `python app.py` 后打开 `http://127.0.0.1:8765/animations/`，不需要模型 Key 或微信联调。可切换待机、生成菜谱、菜谱就绪、跟做等待、做饭完成和连接异常六种状态；支持播放、暂停、逐帧查看、静态模式和下载 SVG。

角色为 Hello Kitty，保留蝴蝶结、椭圆鼻、三根胡须和无嘴造型，搭配小围裙，使用纯黑白粗线条，固定 320×280 画布。源素材是 `animations/frames/` 中 24 个 SVG，定义在 `animations/states.json`，重新生成运行 `python animations/build_frames.py`。间隔 1.8～2.4 秒只是设计值，尚无真机刷新性能依据。

默认待机静止，唤醒时可播一次眨眼；生成菜谱演示最多循环 3 次后停留在等待画面，不会自动进入成功。完成和就绪播放一次；跟做等待和错误保持静止。页面隐藏时停止播放，支持系统减少动态效果偏好。图片本身可以离线保存、复用，无需每次生图。

此页为独立的交互设计预览，尚未接真实菜谱生成任务，也没有替换 Kindle 系统休眠屏保；睡眠状态和网页内等待不同。墨水屏静态保留画面有低功耗优势，但不能据此推断整台设备或浏览器零耗电；具体残影、闪屏、刷新频率与休眠唤醒流程需真机验证。技术依据：https://www.eink.com/tech/detail/FAQ 。

本地运行的原型：微信小程序负责选食材、看推荐、逐步跟做、拍照识别、生图、菜谱管理和 API Token 配置；网页仅作为开发调试入口。

## 微信小程序管理端

源码在 `miniprogram/`，可导入微信开发者工具。`project.config.json` 中的测试 AppID 需替换为你自己的小程序 AppID 后，才能进行对应的真机调试与发布。当前尚未在微信开发者工具编译或真机运行，也未发布。

服务端增加两个配置，独立于 Kindle 设备访问密码：

```powershell
$env:KITCHEN_ADMIN_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))")
$env:KITCHEN_SECRET_KEY = (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python app.py
```

请把这两个值保存到自己的密码管理器或服务端安全配置中，重启时继续设置原值。丢失 `KITCHEN_SECRET_KEY` 后数据库中的模型 Token 将无法解密。不要把这些值写进小程序源码或提交 Git。

在“管理厨房”页填写服务地址和 `KITCHEN_ADMIN_TOKEN`。管理口令只保存在本次小程序内存；模型 Token 通过后端 API 保存，数据库使用 Fernet 认证加密，API 只返回“已配置”状态和固定掩码。模型 Token 可更换、保留或移除；移除只是停止此应用使用它，不是在模型厂商处撤销 Key。已有环境变量中的 Token 也能显示为已配置；小程序保存的配置优先于环境变量。

小程序包含：

- 食材库：拍照/相册上传、文字补充、异步识别、人工确认、添加、改名、删除、图标预览、生成与重新生成。改名同步更新主要食材引用；用量和步骤中的自然语言仍需人工修改。
- 菜谱库：新建、编辑、删除；用量逐行填写，步骤逐行填写；保存后首页刷新即可看到。正在跟做的菜谱禁止编辑或删除，避免步骤错位。
- 模型配置：三路独立的 HTTPS 基址、模型名称、Token；识别/问答可发起少量调用测试连接，图片接口仅检查配置、不冒充成功完成真实连接测试。

开发者工具本机调试可以使用 `http://127.0.0.1:8765`，并在工具中临时关闭合法域名校验；正式环境需要 HTTPS、自己的小程序 AppID 及微信后台对应的 request/uploadFile/downloadFile 合法域名配置。真机上的 127.0.0.1 是手机自身，不能指向电脑。不要把关闭域名校验当作上线方案。

识别和生图以后台任务执行，小程序查询进度，避免单个请求等待完整生图。任务进度暂存在服务内存，服务重启后需重新提交；成功保存的图标和菜谱仍在数据库。任务返回失败时保留旧图，只有新图成功后才替换。

管理接口 `/admin/*` 强制验证独立 Bearer 管理口令（至少 24 字符），即使本机也不匿名开放。当前是单家庭、共享管理口令模式，尚无微信登录、多人权限或按用户隔离；不能直接用作公开多用户服务。Python 内置 HTTP 服务前应由生产级 HTTPS 网关提供访问控制、请求限制与 TLS，勿直接暴露到公网。

## 启动

需要 Python 3.11+。

```powershell
python -m pip install -r requirements.txt
python app.py
```

打开 http://127.0.0.1:8765 。没有 API Key 也能选食材、推荐示例菜谱、跟做和保存进度。

### 手机开发调试

设备与电脑连接同一 Wi-Fi。使用你自己设置的密码：

```powershell
$env:KITCHEN_PASSWORD = '换成你自己的密码'
python app.py --host 0.0.0.0
```

小程序真机不能使用 `127.0.0.1` 访问电脑；开发阶段可通过微信开发者工具关闭本地校验，真机调试应提供可信 HTTPS 地址。若系统防火墙询问，仅允许受信任的家庭专用网络；不要把 Python 内置服务直接映射到公网。

## 接入模型

仅在运行服务端的 PowerShell 设置，禁止把 Key 填入前端代码或提交到仓库：

```powershell
$env:DASHSCOPE_API_KEY = '阿里云百炼北京地域 Key'
$env:DEEPSEEK_API_KEY = 'DeepSeek 官方 Key'
$env:LAS_API_KEY = '火山引擎 LAS 算子调用 Key'
python app.py
```

三个 Key 可独立配置，只开通其中一项也能使用对应功能。默认识别模型 `qwen3-vl-plus`、问答模型 `deepseek-flash`、图标模型 `doubao-seedream-4-5-251128`。生图默认走火山引擎 LAS 算子接口，需要 LAS 的 Key，不能直接把方舟 Key 填到 LAS。已有方舟生图服务时，把 `IMAGE_BASE_URL` 设置为控制台对应的 API 基址并使用匹配 Key。

每路都可分别用 `VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL`、`CHAT_API_KEY` / `CHAT_BASE_URL` / `CHAT_MODEL`、`IMAGE_API_KEY` / `IMAGE_BASE_URL` / `IMAGE_MODEL` 覆盖配置。接口基址必须为 HTTPS；聊天端需兼容 Chat Completions；其他生图端需兼容此 Seedream 请求参数。不要只修改模型名称就切换到不兼容的供应商。

百炼月订阅 Token Plan 也可用于生图：`IMAGE_BASE_URL` 填控制台对应地域的 `https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1`（北京示例），`IMAGE_MODEL` 可填 `qwen-image-3.0-pro`、`wan2.7-image` 或 `wan2.7-image-pro`，`IMAGE_API_KEY` 使用套餐的 `sk-sp-` Key。也可在小程序“模型配置”中填写。该地址使用 DashScope 同步协议，服务端会及时下载有时效的返回图片 URL；Key、地域和接口地址必须一致。

程序不会自动读取 `.env`。如已启动服务，修改环境变量后需要重新启动。API 权限和网络可达性取决于你的账户与运行环境。尚未使用真实 Key 做收费接口联调。

点击“手机食材库”，拍照 / 选照片并补充文字，点击识别。模型只返回候选名称，修改并确认后才加入库。也可直接输入“鸡腿，土豆，鸡蛋”，无需调用识别 API。HEIC 请先转换为 JPEG。

识别、生图、跟做答疑是独立请求，按钮均标注“调用 API”；识别不自动生图。照片会在本机缩小并去除 EXIF 后传给所配置的视觉模型识别，原始照片不落盘。生图使用确认后的标准名称，不把厨房照片作为图标背景。用户点击“生成图片”才调用生图并计入用量。

## 图片如何复用

1. 食材名称归一化：西红柿 → 番茄，洋芋 → 土豆。
2. 根据“标准名称 + 图标提示词全文 + 生图模型 + 生图接口地址”计算缓存键。
3. 已有图片直接返回，不请求模型。
4. 未有图片则生成，缩为 320×320，转纯黑白 1-bit PNG 后保存。
5. 首页和管理页从同一服务读取，关闭重启仍可复用。管理端切换生图模型或提示词不会自动替换现有图；点击“重新生成”并成功后才切换。

Kindle 默认提供 8 个代码绘制的 SVG 示意图，新增食材未生图时显示通用占位图；这些不冒充模型生成图。小程序预览已生成的 PNG，未生成时标注占位状态。可在小程序手动重新生成，首版尚无单独的生图审核流程或历史版本回滚界面。

提示词在 `prompts/` 下，可以当成应用内的轻量 skill 修改：`recognize.txt` 控制识别与命名，`icon.txt` 控制墨水屏图片风格，`assistant.txt` 控制跟做答疑。这里是应用读取的规则文件，不是 Codex 或微信小程序自动执行的 SKILL.md。

## 数据与边界

- `data/kitchen.sqlite3` 持久保存食材、菜谱、PNG 图标、加密模型配置与当前选择、人数、时间、做饭进度；备份需保留数据库和独立保管的加密密钥，在线备份应使用 SQLite backup API。
- 单家庭共享一个进度。页面手动刷新才读取其他设备的最新操作，不做持续轮询。
- 内置 4 道示例菜谱。推荐为本地规则排序，尚非模型自动编菜单；模型用于照片识别、图标生成和当前步骤答疑。
- 人数被保存并显示，但用量仍标注为原菜谱的参考份量，不自动换算。
- 尚未实现计时器、长期口味/过敏档案和做后反馈，不能视为完整成品。
- 小程序首页按请求读取家庭共享进度，未做持续轮询或多人冲突合并。
- 管理端生图/识别使用单工作线程队列，HTTP 请求可并发处理；一个家庭共享状态，尚无多用户会话与冲突合并。

## 检查

```powershell
python -m unittest -v
```

测试用模拟 API 返回值检查图标只生成一次、黑白 PNG 格式、识别归一化及人工确认边界、进度恢复、推荐排序和 HTTP 操作。不会调用收费接口。

国内模型接口参考官方文档：

- https://help.aliyun.com/zh/model-studio/qwen-vl-compatible-with-openai
- https://api-docs.deepseek.com/zh-cn/
- https://docs.volcengine.com/docs/LakeAIService/ImagegenerationSeedreamseriesmodels?lang=zh
