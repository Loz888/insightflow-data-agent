# 启动、迁移、开发重建与恢复

## 本机已有项目
锁定依赖：`python3 -m venv .venv`，`.venv/bin/python -m pip install -r requirements.lock`，
`.venv/bin/python -m pip install --no-deps -e .`。
已有专用库可运行 `sudo .venv/bin/python scripts/upgrade_runtime_db.py`，创建最小Runtime角色并执行有摘要校验的新增迁移。
然后 `.venv/bin/python scripts/migrate_v2.py`；默认不Seed、不删表/库、不重置数据，已应用迁移内容变更会拒绝。
本次已完成无需重新初始化。默认 `./scripts/serve.sh`，页面仅127.0.0.1:8000。
本机.env中已设置Flash Max与共享预算测试控制库；代码/Compose/CI默认Mock。
不要把.env、Bearer或Key提交；.env.example只提供空配置和预算说明。

## 全新本机环境验证
已实际运行 `scripts/fresh_verify.py --output /path/to/NEW-private-audit-directory`。
它用新venv、新PG16 cluster、新端口和四个专用数据库执行CI等价初始化、完整测试、迁移重放及真实HTTP。
原集群不变；临时集群最后停止；不重用已有目标目录；审计目录0700。
需要本机PG16工具和Python，`--output`必须新路径。

## Docker/Compose
`./scripts/start_compose.sh` 自动生成受忽略0600的.env.compose，再docker compose build/up。
随机Owner/Reader/Runtime密码不打印。Docker仅公开回环8000，数据库不映射宿主端口。
普通应用容器非root，Owner只执行启动迁移随后从进程环境移除；生产环境仍应将迁移作业与应用凭据彻底分离。
`docker compose --env-file .env.compose ps` 查看health；静态配置生成/YAML和包资产已检查。
本机无Docker引擎，镜像构建与Compose实际启动为BLOCKED，不能把PG新环境结果替代Docker验证。

## 开发数据与备份
scripts/init_db.sh / scripts/seed_data.py 是显式RESET开发脚本，会清空本项目合成表，不能用作生产迁移。
原五表默认Seed不变，附加表重建也明确列出FK子表，不使用跨Schema CASCADE。
Seed101/202脚本仅对固定两个独立快照库创建数据，已有基表不重置。

备份前停止写入或使用一致性pg_dump：用本机Owner连接配置执行
`pg_dump --format=custom --schema=business --schema=agent_runtime --file=backup.dump`。
通过PGHOST/PGPORT/PGDATABASE/PGUSER与受保护PGPASSFILE提供凭据，避免密码放命令行。
备份含会话问题和证据，文件0600且不进Git。`pg_restore --list backup.dump` 可先只读核查。
恢复应由管理员在新的隔离数据库演练，再核对迁移版本、表计数、独立参考结果和认证所有权；
不要对正在演示的库直接使用--clean。恢复本身本轮NOT_RUN。

## CI
更新后的ci.yml包含原回归、V2、真实PG、双Seed、静态检查和离线评测；付费Key为空。
本地全新环境已运行等价步骤。按用户要求不推送，因此V2远程Actions为NOT_RUN；
旧main绿色CI属于旧版本，不能冒充V2结果。Live入口为本地显式脚本，常规CI不付费。
