# 基于STM32F413ZH与OneNET的智能骑行头盔

本项目是一个针对夜间骑行安全的物联网原型系统。系统通过多传感器融合技术实时监测骑行状态，并在检测到危险（如摔倒或靠近障碍物）时，通过灯光、语音和云平台发出多级警报。

## 功能特性

- **多源数据采集**：集成VL53L1X测距、温湿度、光照、六轴姿态（LIS2DH12）及GPS（GNSS）定位。
- **实时状态识别**：识别正常、左/右转、边距警告（<1m）及摔倒共6种状态。
- **多模态反馈**：根据状态自动控制WS2812B灯带（流水灯/呼吸灯）并触发语音播报。
- **云端联动**：通过4G模块（Quectel）连接OneNET平台，常规数据30秒上报，危险事件秒级紧急上报。
- **远程监护**：微信小程序实时同步头盔状态，摔倒时主动推送报警通知（由队友开发）。

## 技术栈

- **主控**：STM32F413ZH (Cortex-M4)
- **开发环境**：MicroPython / STM32Programmer
- **关键外设**：VL53L1X (测距) / LIS2DH12 (姿态) / WS2812B (灯带) / GNSS (定位)
- **通信协议**：MQTT over 4G (Quectel EC800M)
- **云平台**：OneNET

## 项目结构
```
STM32-OneNET-SmartHelmet/
├── main.py          # 主程序入口，包含任务调度与核心逻辑
├── vl53l1x.py       # 激光测距传感器驱动
├── config.py        # 云平台密钥配置（不上传，需自行创建）
└── README.md        # 项目说明
```

## 快速开始

### 1. 环境准备
- 硬件：STM32F413ZH开发板 + UniKnect Gen1 Pro扩展板
- 固件：烧录MicroPython固件

### 2. 配置密钥
在项目根目录下创建 `config.py` 文件，填入以下信息：
```python
ONENET_BROKER = 'studio-mqtt.heclouds.com'
ONENET_PORT = 1883
ONENET_USERNAME = 'your_username'
ONENET_CLIENT_ID = 'your_device_id'
ONENET_PASSWORD = 'your_password'
```

### 3. 运行程序
将代码上传至开发板，执行 `main.py` 即可。

## 演示视频

[点击观看B站演示视频] https://b23.tv/yMEJBPL

## 项目成果

- 该系统作为核心作品参加[全国大学生物联网设计竞赛]。
- 摔倒检测响应时间 < 1秒，边距警告准确率 > 95%。

## 后续优化方向

- [ ] 优化跌倒检测算法，进一步降低误报率。
- [ ] 增加短信报警功能，提高可靠性。

## 作者

- GitHub: https://github.com/920787647
- B站: https://b23.tv/3qENM1M