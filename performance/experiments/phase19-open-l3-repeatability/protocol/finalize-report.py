import os,json,hashlib,subprocess
from pathlib import Path
root=Path.cwd();out=root/'performance/experiments/phase19-open-l3-repeatability';old=root/'performance/experiments/phase19-availability-fault-fix'
sha=lambda b:hashlib.sha256(b).hexdigest()
git=lambda *args:subprocess.check_output(['git',*args],text=True).strip()
q=json.loads((out/'qualification.json').read_text());rounds=json.loads((out/'round-summary.json').read_text())
assert git('rev-parse','HEAD:backend')==git('rev-parse','98e3d2aa22d6015664bb995708c23800f1e1a456:backend')
prior=sha((old/'Manifest.json').read_bytes());assert prior=='c93868ebd45367b4afc70bffe03066c80e9464421f533a5405e137410b18a686'
metadata={'backendProductionSourceCommit':'98e3d2aa22d6015664bb995708c23800f1e1a456','backendGitTree':git('rev-parse','HEAD:backend'),'checkoutCommitAtAllThreeSetups':'ee8ed47c6e8cce02c67113e6c4a5e126cdda9894','qualificationToolingCommit':git('rev-parse','HEAD'),'backendBinarySha256':'0db6f0c3850ac0c91e40a271dc9ca60f021fda315e7c80a9b2fcb427c67f067a','productionSourceAndBinaryUnchanged':True,'priorManifestSha256':prior,'frozenProtocolManifestSha256':sha((root/'performance/experiments/phase19-global-polling-mixed-load/protocol-sha256.json').read_bytes()),'roundsPlanned':3,'roundsExecuted':3,'qualified':q['qualified'],'newGateTests':12,'performancePythonTests':335,'protection':'all event policies OFF; process-local Availability Bulkhead 16 unchanged','generator':'2 CPU / 4 GiB; existing qualified identity unchanged','sequence':'precheck -> L1 -> L2 -> L3; each point exactly once per fresh environment','initialNormalization':'Only fresh generation UUIDs, stream timestamp IDs, observation UTC, and round-specific frontend origin normalized. Inventory/profile fingerprints, model readiness, stream lengths/counts, formal versions, all remaining runtime config and binary hash retained. No old application cache/data/process reused. OS page cache and host scheduling are not controlled.','newObservation':'Same additional read-only cpu.stat and filtered Redis SLOWLOG sampling for each L3, every 10 seconds; frozen load generation unchanged. No Redis arguments/credentials recorded.','reuseOfEarlierGates':'Backend 166/166 closed by user. Existing 2000 VU 10 min, 5001 business iterations, 1000 VU hotspot and overload/financial gates use identical production source tree and binary and are not rerun.','historicalLimits':'Exact Zone and server admission-time queue/pool trace were not recorded. Old failure direct condition is 16 occupied Availability permits; ultimate source of transient latency is not uniquely established.'}
(out/'summary.json').write_bytes((json.dumps(metadata,indent=2)+'\n').encode())
rows=[]
for i,r in enumerate(rounds,1):
 p=r['points'][-1];rows.append(f"| 独立轮次 {i} | {p['deltaPerSecond']:.3f} | {p['writePerSecond']:.3f} | {p['http503']:.0f} | {p['dropped']} / {p['interrupted']} | {p['observe503ErrorRate']*100:.6f}% | {'PASS' if p['valid'] and p['inventoryPassed'] else 'FAIL'} |")
conclusion='三轮独立的 precheck → L1 → L2 → L3 全部通过，达到本次要求的三轮重复性资格。' if q['qualified'] else '三轮独立资格未通过，停止追加尝试；不以重试到通过代替稳定容量证据。'
report=f'''{conclusion} 本次未修改后端生产源码或配置，未调整 Bulkhead=16、500 Delta/s、42.85 写请求/s，也未调整请求起发、预热或观察时长。

| 场景 | Delta/s | 写请求/s | HTTP 503 | dropped / interrupted | 观察窗 503 错误率 | 冻结门禁与库存 |
|---|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

每轮均为全新 PostgreSQL 数据卷、空 Redis 和新 API 进程，在上一轮容器停止后开始。初始协议验证会建立 5 个读模型；三轮都保留这个相同的既定步骤。初始清单为 5000 用户、5 场次共 25000 座位、正式版本总和 0、25 条初始流记录，库存指纹一致。generation UUID、流时间戳及前端端口自然不同，原始值全部保留，比较时规范化；其余配置和数据指纹不变。完整初态、容器/卷/网络身份、边界指标、12 个负载点结果和 SQL/Redis 验证均归档。

历史 r1 的 8 次 Availability Bulkhead 503 完整保留，观察窗错误率为 8/43765=0.018279%，原门禁中止，28 个 interrupted；旧 r2 同环境通过也保留，但不计入本次三轮独立资格。直接触发条件是 16 个在途许可已占用，客户端区间重建与后续服务端峰值/拒绝计数一致。没有发现持续许可泄漏、重新集中初始化或 generation 重建证据；r1 失败时成功 Delta 尾部耗时约 40–45 ms。更下游停顿原因未被旧数据唯一定位，具体 Zone 和瞬时计算/数据库连接池队列也无法事后恢复。详见 DIAGNOSIS.md；未知项没有被填成零或猜测值。

本次三轮结果只证明指定环境与冻结序列的重复性，不抹去历史波动，也不构成任意运行时长下零过载的保证。资格结果由 qualification.json 单独记录；12 项新增校验测试包含拒绝暖环境复用、改顺序、先失败再追加通过、低于目标速率、缺失/非有限数值及库存不一致。

准确生产源码提交：`{metadata['backendProductionSourceCommit']}`；backend Git tree：`{metadata['backendGitTree']}`；实际后端二进制 SHA-256：`{metadata['backendBinarySha256']}`。三轮 setup 的 Git HEAD 均为 `{metadata['checkoutCommitAtAllThreeSetups']}`，其 backend 树与上述生产提交完全相同。资格校验器提交：`{metadata['qualificationToolingCommit']}`。完整 Python 性能/协议测试 335/335，通过日志见 verification/python-full.log。原后端 166/166 及使用相同二进制通过的 2000 VU、5001 次业务、1000 VU 热点、过载和金融恢复结果继续适用，按本次授权未重复运行。

旧证据目录和旧 Manifest 均未修改；旧 Availability 修复 Manifest SHA-256 为 `{prior}`。本目录 Manifest.json 绑定生产源码、二进制、冻结协议与新增文件 SHA-256；Manifest 不包含自身，避免循环哈希。各点完整 k6 原始 gzip 留在本机私有目录，路径、大小和 SHA 记录在各点 archive-manifest.json，已逐一核对。普通 commit 与 push 后的准确证据提交 SHA 和 Git 状态由交付回复给出，不 merge main、不创建 PR、不 force push。材料供下一独立会话最终复验，本会话未声称已完成该独立复验。
'''
(out/'REPORT.md').write_bytes(report.encode())
if not q['qualified']:
 highest=next((n for n in ['l2','l1','precheck'] if all(next(p for p in r['points'] if p['name']==n)['valid'] for r in rounds)),None)
 with (out/'REPORT.md').open('a',encoding='utf8') as f:f.write(f'\n最高三轮可重复档位：{highest}。建议简历使用该档位；如描述 L3，应明确“达到 500 次/秒但观察到少量过载拒绝”。\n')
manifest={'backendProductionSourceCommit':metadata['backendProductionSourceCommit'],'backendBinarySha256':metadata['backendBinarySha256'],'qualificationToolingCommit':metadata['qualificationToolingCommit'],'priorManifestSha256':prior,'scope':'New independent Open L3 evidence; all old failures and manifests immutable','files':{}}
for p in sorted(out.rglob('*')):
 if p.is_file() and p.name!='Manifest.json':manifest['files'][p.relative_to(out).as_posix()]={'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
p=out/'Manifest.json';assert not p.exists();p.write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
print('MANIFEST',sha(p.read_bytes()),'FILES',len(manifest['files']))
