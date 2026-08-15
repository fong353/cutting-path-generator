# 切割路径生成器（已归档）

**2026-08-15 归档。** 卡纸拼板出 EPS 已并入 [`ru-dan-web`](https://github.com/fong353/ru-dan-web)（生产在 `wyse`），本仓与 cutter 上的独立 Web **不再使用、不要再部署**。

现役入口：入单系统「卡纸拼版」标签；核心在 `ru-dan-web/server/ru_dan_server/cutting/`。

## cutter 上留下的东西（回滚用）

主机仍是公司切割机台，SSH 别名 `cutter`（`192.168.0.115`，经 `mac-company` 或 `wyse-tailnet` 跳）。**不要删 SSH。**

归档时做了：

- 停并 **Disable** 计划任务 `CuttingPathGenerator`（未删任务定义）
- 删防火墙规则 `CuttingPathGenerator`（TCP 8080）
- 目录 `C:\cutting-path-generator`（含 `.venv`、`data/`）原样保留
- 生产 `data/` 副本在本机 `data/archive-20260815/`（gitignore，不进 git）

若必须临时恢复旧服务：

```text
ssh -o ProxyJump=wyse-tailnet cutter
netsh advfirewall firewall add rule name=CuttingPathGenerator dir=in action=allow protocol=TCP localport=8080
schtasks /Change /TN CuttingPathGenerator /ENABLE
schtasks /Run /TN CuttingPathGenerator
```

健康检查：`http://192.168.0.115:8080/`（无 `/health`，首页 200 即可）。不要跑 `./deploy_to_cutter.sh`，除非 Nate 明确要求恢复。

## 历史摘要（只读）

曾是公司内网独立服务：业务员 `/sales` 提需求，操作员 `/ops` 按材料混拼出 EPS。拼板算法与 EPS 三色 Separation 已迁入 ru-dan-web，勿在本仓继续改功能。
