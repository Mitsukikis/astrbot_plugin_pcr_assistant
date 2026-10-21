# NOTICE

`astrbot_plugin_pcr_assistant` 是一个非官方 AstrBot 插件，用于个人服务器上的公主连结相关自动化辅助。

## 参考与借鉴

- AstrBot: <https://github.com/AstrBotDevs/AstrBot>
  - 本项目是 AstrBot 插件，遵循其插件目录、`metadata.yaml` 和 WebUI 配置方式。
- AutoPCR: <https://github.com/cc004/autopcr>
  - 本项目通过 AutoPCR Web 提供清日常入口。
  - `sidecar/pcr_real_api.py` 运行在 AutoPCR 镜像内，用于读取真实竞技场和会战数据。
  - AutoPCR 使用 CC BY-NC-SA 4.0 授权，请遵守其原项目许可。
- pcrdfans.com: <https://www.pcrdfans.com/>
  - “怎么拆/竞技场作业”功能调用 pcrdfans Bot API。
  - 本项目不打包 pcrdfans 数据，也不绕过 API Key。
  - 可选网页模式仅匿名访问公开页面，返回当前查询少量结果截图并标注来源；站点限制访问时停止。网页截图不随代码或发布包分发。
- KokkoroBot: <https://github.com/zzbslayer/KokkoroBot>
  - 本项目参考了 PCR QQ 机器人生态里的竞技场作业查询体验。
  - 角色别名/阵容解析相关数据和思路参考 KokkoroBot，KokkoroBot 使用 GPL-3.0 授权。
- redive.estertion.win: <https://redive.estertion.win/>
  - 图片阵容识别会在运行时下载角色头像作为本地缓存。
- 花舞公开文档: <https://docs.hwmoe.com/zh/cygames/pcr/auto_report_knife>
  - 仅参考公开命令及监控交互，不包含或声称获得其私有后端源码。
- HoshinoBot: <https://github.com/Ice-Cirno/HoshinoBot>；yobot_remix: <https://github.com/eggggi/yobot_remix>
  - 参考 GPL-3.0 开源生态的会战协作及作业查询行为，未复制整个后端，数据不互通。
- PCRJJCAnalyzer: <https://github.com/Alive24/PCRJJCAnalyzer>
  - 参考 OpenCV 头像识别思路；本项目新增本地多变体模板、完整布局与低置信度拒识校验。

## 第三方权利

《公主连结 Re:Dive》及相关角色、图像、名称归其权利方所有。本项目仅供学习、自用和小范围群管理，不是官方服务。

图标素材由使用者提供，仓库维护者不声明对该素材拥有版权。
