# BU01/DW1000 TWR 诊断增强版固件方案

## 1. 升级目标

本方案在现有 BU01 四锚点 SS-TWR 测距系统基础上，增加 DW1000 接收诊断信息输出，用于判断测距是否受到 NLOS、强多径、天线姿态变化或遮挡影响。

升级后的系统仍保持当前五节点架构：

- A0：网关锚点，连接电脑串口，负责接收 TAG 汇总数据并输出 CSV。
- A1/A2/A3：普通锚点，只响应指向自己的 TWR poll。
- TAG：依次测量 A0/A1/A2/A3 距离，并将四路距离和诊断信息通过 UWB 发给 A0。

本次升级不改变 TWR 主流程，而是在每次 TAG 收到锚点 response 后读取 DW1000 诊断寄存器，随距离一起上传。

## 2. 测距算法保持 SS-TWR

每一路距离仍采用单边双向测距 SS-TWR：

```text
TAG -> ANCHOR: poll
ANCHOR -> TAG: response，携带 poll_rx_ts 和 resp_tx_ts
TAG: 读取 poll_tx_ts、resp_rx_ts，并结合 response 中的两个时间戳计算 ToF
```

计算公式：

```text
rtd_init = resp_rx_ts - poll_tx_ts
rtd_resp = resp_tx_ts - poll_rx_ts
tof = (rtd_init - rtd_resp * (1 - clock_offset_ratio)) / 2
distance = tof * SPEED_OF_LIGHT
```

其中 `clock_offset_ratio` 来自 `dwt_readcarrierintegrator()`，用于降低 SS-TWR 中两端晶振频偏造成的误差。

## 3. 新增 DW1000 诊断信息

TAG 每次成功收到某个锚点 response 后调用：

```c
dwt_readdiagnostics(&raw);
```

读取以下关键字段：

- `firstPathAmp1/2/3`：首径附近三个采样点幅度。
- `maxGrowthCIR`：接收 CIR 能量相关指标，用于估算总接收功率。
- `rxPreamCount`：接收累积的前导码符号数量。
- `firstPath`：首径索引，10.6 位定点格式。

固件进一步计算：

```text
rx_power_cdbm = 总接收功率，单位 0.01 dBm
fp_power_cdbm = 首径功率，单位 0.01 dBm
power_gap_cdb = rx_power - fp_power，单位 0.01 dB
fp_index_q6 = 首径索引原始值，除以 64 后为采样索引
rx_pream_count = 前导码累积数量
```

## 4. NLOS/多径判断逻辑

核心指标是：

```text
power_gap = rx_power - fp_power
```

解释：

- `rx_power` 表示整包信号总能量，包含直达路径和反射路径。
- `fp_power` 表示最早到达路径的能量。
- 如果 `rx_power` 很强但 `fp_power` 很弱，说明总能量可能主要来自反射路径。

经验判断：

```text
gap < 6 dB：通常较可信
6 dB <= gap < 10 dB：可能存在多径，需要观察
gap >= 10 dB：高度怀疑 NLOS 或强多径
```

固件当前将 `gap > 10 dB` 标记为可疑，但最终阈值需要通过现场数据校准。

## 5. 新串口输出格式

A0 网关输出从旧版：

```text
RANGE4,seq,d0,d1,d2,d3,status,pc_ms
```

升级为：

```text
RANGE4D,seq,d0,d1,d2,d3,status,pc_ms,
rxpwr0,fppwr0,gap0,fpidx0,rxpacc0,
rxpwr1,fppwr1,gap1,fpidx1,rxpacc1,
rxpwr2,fppwr2,gap2,fpidx2,rxpacc2,
rxpwr3,fppwr3,gap3,fpidx3,rxpacc3
```

其中：

- `d0~d3`：TAG 到 A0/A1/A2/A3 的距离，单位 cm。
- `rxpwr*_cdbm`：总接收功率，单位 0.01 dBm。
- `fppwr*_cdbm`：首径功率，单位 0.01 dBm。
- `gap*_cdb`：总功率与首径功率差，单位 0.01 dB。
- `fpidx*_q6`：首径索引，实际值为 `fpidx / 64`。
- `rxpacc*`：接收前导码累积数量。

## 6. 上位机数据保存

实时读取脚本：

```powershell
cd E:\a_ST\毕业设计
powershell -ExecutionPolicy Bypass -File .\tools\uwb_realtime_reader.ps1 -PortName COM7 -CsvPath .\data\uwb_live_diag.csv
```

脚本会保存 `RANGE4D` 的所有诊断字段，并在终端显示四路 `gap_db`，方便快速判断哪一路锚点受多径影响最大。

3D 重建脚本已经兼容 `RANGE4D`：

```powershell
&E:\Anaconda\python.exe .\tools\uwb_trilateration_3d.py --input .\data\uwb_live_diag.csv --anchors .\config\anchor_positions.csv --output .\data\uwb_position3d_diag.csv
```

## 7. 天线延迟标定计划

当前固件仍使用默认天线延迟：

```c
TX_ANT_DLY = 16436
RX_ANT_DLY = 16436
```

后续标定流程：

1. 在开阔 LOS 环境下固定 TAG 和一个锚点。
2. 用卷尺设置 2m、4m、6m、8m 等真实距离。
3. 每个距离采集 300 条以上数据。
4. 使用中位数作为该距离测距结果。
5. 若所有距离稳定偏大，调整天线延迟参数；若稳定偏小，反向调整。
6. 标定完成后，再结合 `dwt_getrangebias()` 做距离相关偏置修正。

## 8. 预期效果

本次升级的预期效果：

- 能判断某一路距离跳变是否由 NLOS/多径引起。
- 能记录每个锚点的信号质量，为后续异常剔除提供依据。
- 能在图形化界面中显示锚点质量状态，例如绿色/黄色/红色。
- 能为天线延迟标定和场地部署提供数据支撑。
- 能减少“裸距离直接重建 3D 坐标”导致的坐标拉飞问题。

需要注意：

- 诊断信息本身不会自动让距离变准。
- 它的作用是识别坏数据、降低坏数据权重、指导现场摆放和标定。
- 真正提升稳定性还需要结合天线延迟标定、range bias 修正、中值滤波、速度约束和残差剔除。

