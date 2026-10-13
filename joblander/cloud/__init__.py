"""多租户形态（GCP）的接线：存储后端、账户令牌、引擎与任务服务的入口、开通 / 删除 / 迁移。

同一个镜像按 JOBLANDER_ROLE 跑成两种服务：
- engine：用户界面与 API（经网关转发，每个请求带账户令牌）。
- worker：内部接口（开通 / 删除 / 导入导出账户、调度扇出、按账户跑一轮调度），只接受
  网关、Cloud Scheduler、Cloud Tasks 的服务账号调用（Cloud Run IAM）。
"""
