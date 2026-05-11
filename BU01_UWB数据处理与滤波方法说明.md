# BU01 UWB 数据处理与滤波方法说明

本文档说明当前项目从 A0 串口 `RANGE4D` 原始距离数据，到 3D 坐标重建、异常剔除、插值和平滑可视化的完整流程。

## 1. 总体处理链路

```text
RANGE4D 原始 CSV
  -> 距离偏置修正
  -> 距离层短异常处理
  -> 3D 坐标重建
  -> 先按 RMS 绝对剔除坏点
  -> 只用 RMS 正常点做邻域/速度/加速度判断
  -> 异常点保留占位并插值修复
  -> 中值平滑 + Alpha-Beta 平滑
  -> 图形界面显示
```

对应脚本：

```text
tools/uwb_apply_range_bias.py
tools/uwb_filter_ranges.py
tools/uwb_trilateration_3d.py
tools/uwb_filter_positions.py
tools/uwb_process_and_visualize.py
tools/uwb_trajectory_visualizer.py
```

## 2. 原始 RANGE4D 数据

主要格式：

```text
RANGE4D,seq,d0_cm,d1_cm,d2_cm,d3_cm,status_hex,pc_ms,diagnostics...
```

字段含义：

```text
seq: TAG 测距序号，0-255 循环
d0_cm: TAG 到 A0 的距离，单位 cm
d1_cm: TAG 到 A1 的距离，单位 cm
d2_cm: TAG 到 A2 的距离，单位 cm
d3_cm: TAG 到 A3 的距离，单位 cm
status_hex: 四路测距成功状态位
pc_ms: 主控运行毫秒计时，用于估算相邻点时间间隔
diagnostics: DW1000 诊断信息，例如接收功率、首径功率、power gap
```

图形界面额外生成 `idx`，这是整份文件中的唯一行号，不会像 `seq` 一样回绕。

## 3. 距离偏置修正

脚本：

```text
tools/uwb_apply_range_bias.py
```

当前默认：

```text
--bias-cm -30
```

含义是对 `d0_cm` 到 `d3_cm` 统一减去 30 cm。它是经验偏置修正，不等价于严格的每链路天线延迟标定。

## 4. 距离层异常处理

脚本：

```text
tools/uwb_filter_ranges.py
```

当前默认参数：

```text
--max-jump-cm 220
--smooth-window 1
--neighborhood 4
--max-interp-run 3
```

### 4.1 距离层异常检测

对 `d0_cm`、`d1_cm`、`d2_cm`、`d3_cm` 每一路单独处理。

对第 `i` 个距离点，取前后邻域：

```text
i-4, i-3, i-2, i-1, i+1, i+2, i+3, i+4
```

计算邻域中位数 `baseline`。如果：

```text
abs(value - baseline) > 220 cm
```

则认为该路距离在这一帧出现明显跳变。

注意：距离层当前只处理很大的距离跳变，主要是为了先去掉明显坏点；几十厘米级的抖动更多交给 3D 层的 RMS、速度和加速度规则处理。

### 4.2 距离层插值

距离层有插值，但只修复短异常段：

```text
--max-interp-run 3
```

也就是连续 1 到 3 个距离异常点会被线性插值。连续异常超过 3 个点则不在距离层强行修复，避免把长时间 NLOS 或真实变化硬补成假数据。

当前距离层平滑窗口是：

```text
--smooth-window 1
```

等于不做距离层中值平滑，避免过早平滑影响后续 3D 层判断。

## 5. 三维坐标重建

脚本：

```text
tools/uwb_trilateration_3d.py
```

输入：

```text
d0_cm, d1_cm, d2_cm, d3_cm
config/anchor_positions.csv
```

理论模型：

```text
|P - A0| = d0
|P - A1| = d1
|P - A2| = d2
|P - A3| = d3
```

程序先线性化求初值，再用迭代最小二乘优化：

```text
min sum(weight_i * (|P - Ai| - di)^2)
```

当前默认启用：

```text
--z-min 0
```

即 `z >= 0`，避免出现地下点。

## 6. 诊断权重

如果原始数据中有 `gap0_cdb` 到 `gap3_cdb`，3D 重建会按 power gap 降低疑似多径锚点的权重。

当前规则：

```text
gap <= 6 dB: weight = 1.0
gap >= 14 dB: weight = 0.10
6 dB < gap < 14 dB: weight 从 1.0 线性下降到 0.10
```

含义是：接收总功率和首径功率差距越大，多径/NLOS 风险越高，该锚点距离在最小二乘中的影响越低。

## 7. RMS 的含义

3D 重建后，每个点都会输出：

```text
rms_error_m
```

计算方式：

```text
res_i = |P - Ai| - di
rms = sqrt((res_0^2 + res_1^2 + res_2^2 + res_3^2) / 4)
```

直观理解：

```text
rms 越小，说明重建点和四路距离越一致
rms 越大，说明四路距离之间矛盾越大
```

经验范围：

```text
rms < 0.10 m: 很好
0.10 m <= rms < 0.30 m: 可用
0.30 m <= rms < 0.50 m: 可疑
rms >= 0.50 m: 较差，通常需要检查多径、锚点坐标或距离偏置
```

当前默认阈值：

```text
--max-rms-m 0.30
```

同时增加一层局部相对 RMS 过滤：

```text
--rms-local-neighborhood 10
--rms-local-ratio 3.0
--rms-local-delta-m 0.08
--rms-local-min-m 0.12
```

它用于处理“整体 RMS 不高，但局部明显比周围高”的点。例如周围大多数点是 `0.03-0.06m`，中间连续几帧是 `0.18-0.28m`，这些点虽然没有超过绝对阈值 `0.30m`，但会因为相对周围明显异常而被标记为 `rms_local`。

局部 RMS 判断只使用已经通过绝对 RMS 检查的正常点作为邻居，避免坏点污染邻域基准。

## 8. 当前 RMS 过滤策略

当前已经改为严格策略：

```text
先将 rms_error_m > 0.30 m 的点全部标记为异常
```

这些高 RMS 点不会参与后续邻域判断，也不会作为速度/加速度判断的前后参考点。

这一步很重要，因为如果连续几个异常点混入邻域，中位数会被污染，坏点可能反而被保留下来。现在的做法是先建立“RMS 正常点集合”，后续判断只使用这个集合。

输出中新增：

```text
raw_rms_error_m
```

它表示修复前原始 RMS。对于被短异常插值修复的点，`rms_error_m` 会改为邻近正常点的插值 RMS，`raw_rms_error_m` 保留原始坏值，方便追踪。

## 9. 3D 坐标层异常处理

脚本：

```text
tools/uwb_filter_positions.py
```

当前默认参数：

```text
--max-step-m 1.20
--max-rms-m 0.30
--smooth-window 3
--neighborhood 4
--max-interp-run 3
--max-speed-mps 3.0
--max-accel-mps2 18.0
--alpha 0.45
--beta 0.08
--z-drop-step-m 0.20
```

图形界面的运动模式会覆盖速度、加速度和 alpha/beta：

```text
慢走: v<=2m/s,  a<=3m/s^2,  alpha=0.42, beta=0.06
跑步: v<=6m/s,  a<=6m/s^2,  alpha=0.45, beta=0.08
快跑: v<=8m/s,  a<=8m/s^2,  alpha=0.48, beta=0.09
球:   v<=35m/s, a<=30m/s^2, alpha=0.55, beta=0.12
```

### 9.1 局部邻域判断

当前点只有在 RMS 正常时才会进入局部邻域判断。

邻居也只从 RMS 正常点中选择：

```text
neighbors = 前后 4 帧范围内 RMS 正常的点
```

然后计算这些正常邻居的 x/y/z 中位数。如果当前点到邻域中位数距离超过：

```text
1.20 m
```

则标记为：

```text
isolated_jump
```

### 9.2 速度和加速度判断

速度/加速度判断也只使用正常点作为前后参考。

对当前点，寻找前一个正常点 `prev` 和后一个正常点 `next`，计算：

```text
v_prev = distance(prev, current) / dt_prev
v_next = distance(current, next) / dt_next
v_bridge = distance(prev, next) / (dt_prev + dt_next)
```

如果当前点导致前后速度都超阈值，而 `prev -> next` 本身是合理的，则认为当前点是尖峰：

```text
speed_spike
```

加速度规则类似，如果当前点造成不合理加速度，而前后正常点之间仍连贯，则标记为：

```text
accel_spike
```

## 10. 插值和占位修复规则

当前 3D 层不再直接删除异常点，而是保留行占位并插值修复：

```text
连续异常长度 <= 3: 标记 interp，并插值修复
连续异常长度 > 3: 标记 long_interp，并继续用前后正常点插值/保持修复
```

插值方式：

```text
左右都有正常点: x/y/z/rms 线性插值
只有左侧正常点: hold_prev
只有右侧正常点: hold_next
```

如果长异常段左右都有正常点，则整段按左右正常点线性插值；如果只找到一侧正常点，则使用 `hold_prev` 或 `hold_next` 保持最近正常点。这样表格中的 index/sequence 仍然连续，图形界面也不会因为删除行导致时间轴缺口。

## 11. z=0 处理

图形界面有两个选项：

```text
过滤 z=0 点
删除全部 z=0 点
```

过滤 z=0 点：

```text
--filter-z-floor
```

`z <= 0.02m` 会被标记为异常，然后进入占位插值修复流程。

删除全部 z=0 点：

```text
--drop-z-floor
```

`z <= 0.02m` 在进入其他滤波前直接删除。

## 12. 平滑

异常处理后执行两步平滑。

第一步是 3 点中值平滑：

```text
--smooth-window 3
```

第二步是 Alpha-Beta 平滑：

```text
alpha: 位置跟随测量值的强度
beta: 速度估计更新强度
```

alpha/beta 越大，轨迹越灵敏；越小，轨迹越平滑但延迟更明显。

## 13. 输出文件

一键处理输出：

```text
*_bias_minus30.csv
*_bias_minus30_range_filtered.csv
*_position3d_range_filtered_z0_weighted.csv
*_position3d_range_filtered_z0_weighted_filtered.csv
```

最终用于可视化的是：

```text
*_position3d_range_filtered_z0_weighted_filtered.csv
```

重要字段：

```text
x_m, y_m, z_m: 最终显示坐标
rms_error_m: 修复/过滤后的 RMS 显示值
raw_rms_error_m: 修复前原始 RMS
filtered_flag: 该点是否被 rms_abs、rms_local、isolated_jump、speed_spike、interp、long_interp 等规则处理过
```

## 14. 当前策略总结

当前策略核心是：

```text
先剔除高 RMS 坏点
再剔除局部 RMS 相对异常点
只用好点作为邻域和运动判断参考
坏点保留占位并插值修复
最后再做轻平滑
```

相比之前只扩大邻域的做法，新策略能避免连续异常点污染邻域中位数，更适合 20Hz 数据。
