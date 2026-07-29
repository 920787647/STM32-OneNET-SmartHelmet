import machine
import time
import json
import urandom
import math
import _thread
import quectel
from ahtx0 import AHT20
from lis2dh12 import LIS2DH12
from st7735 import LCD
from umqtt.robust import MQTTClient
from vl53l1x import VL53L1X
from quectel import Audio
from config import *

# ==================== 全局 GNSS 数据与线程控制 ====================
gnss_data = {
    "lat": 0.0, "lon": 0.0, "alt": 0.0, "speed": 0.0,
    "lat_dir": "N", "lon_dir": "E", "fixed": False
}
gnss_running = True

def gnss_loop():
    global gnss_data, gnss_running
    gnss_obj = None
    try:
        gnss_obj = quectel.GNSS()
        if not gnss_obj.start():
            print("GNSS 模块启动失败！")
            return
        print("后台 GNSS 定位线程启动成功...")

        while gnss_running:
            try:
                loc = gnss_obj.get_location()
                if loc and "latitude" in loc and "longitude" in loc:
                    raw_lat = float(loc["latitude"])
                    raw_lon = float(loc["longitude"])
                    alt = float(loc.get("altitude", 0.0))
                    speed = float(loc.get("speed", 0.0))

                    gnss_data["lat"] = abs(raw_lat)
                    gnss_data["lon"] = abs(raw_lon)
                    gnss_data["lat_dir"] = "N" if raw_lat >= 0 else "S"
                    gnss_data["lon_dir"] = "E" if raw_lon >= 0 else "W"
                    gnss_data["alt"] = alt
                    gnss_data["speed"] = speed
                    gnss_data["fixed"] = True
                else:
                    gnss_data["fixed"] = False

                for _ in range(20):  # 每2秒更新一次定位
                    if not gnss_running:
                        break
                    time.sleep(0.1)
            except Exception as e:
                print("GNSS 读取异常:", e)
                time.sleep(1)
    finally:
        if gnss_obj:
            try:
                gnss_obj.stop()
                print("GNSS 线程已安全停止")
            except Exception:
                pass

# 启动后台 GNSS 线程
try:
    _thread.stack_size(4096)
    _thread.start_new_thread(gnss_loop, ())
    print("后台定位线程已创建。")
except Exception as e:
    print(f"创建定位线程失败: {e}")

# ==================== 语音播报初始化 ====================
def speak_cloud_connected():
    print("准备播报云平台连接提示音...")
    audio = None
    try:
        audio = Audio()
        if audio.init(None):
            audio.set_speaker_volume(5)
            audio.tts_set_volume(90)
            audio.tts_set_speed(65)
            
            prompt_text = "智能头盔已连接云平台，安全系统初始化成功。"
            print(f"正在播报: '{prompt_text}'")
            audio.tts_play(prompt_text)
            
            time.sleep(3.5)
            print("连网提示音播报完毕！")
        else:
            print("Audio 模块初始化失败，跳过语音提示。")
    except Exception as e:
        print(f"语音播报异常: {e}")
    finally:
        if audio:
            try:
                audio.deinit()
            except Exception:
                pass
        time.sleep(0.5)

# ==================== 灯光控制类 ====================
class WS2812_Official_Bitstream:
    def __init__(self, pin_str, num_leds=8):
        self.pin = machine.Pin(pin_str, machine.Pin.OUT)
        self.pin.value(0)
        self.num_leds = num_leds
        self.buf = bytearray(num_leds * 3)

    def set_all(self, r, g, b):
        for i in range(self.num_leds):
            self.buf[i * 3 + 0] = g
            self.buf[i * 3 + 1] = r
            self.buf[i * 3 + 2] = b

    def set_pixel(self, idx, r, g, b):
        if 0 <= idx < self.num_leds:
            self.buf[idx * 3 + 0] = g
            self.buf[idx * 3 + 1] = r
            self.buf[idx * 3 + 2] = b

    def show(self):
        timing = (350, 800, 800, 350)
        machine.bitstream(self.pin, 0, timing, self.buf)

try:
    strip_left = WS2812_Official_Bitstream('PG0', 8)
    strip_right = WS2812_Official_Bitstream('PG1', 8)
except Exception:
    strip_left = WS2812_Official_Bitstream('G0', 8)
    strip_right = WS2812_Official_Bitstream('G1', 8)

C_OFF    = (0, 0, 0)
C_RED    = (255, 0, 0)
C_GREEN  = (0, 20, 0)     
C_YELLOW = (255, 150, 0)
C_WHITE  = (30, 30, 30)

led_status = 0
try:
    led_red = machine.Pin('LED_RED', machine.Pin.OUT)
    led_red.value(led_status)
except Exception:
    led_red = machine.Pin(2, machine.Pin.OUT) 
    led_red.value(led_status)

# ==================== 云平台配置 ====================

BROKER = ONENET_BROKER
PORT = ONENET_PORT
USERNAME = ONENET_USERNAME
CLIENT_ID = ONENET_CLIENT_ID
PASSWORD = ONENET_PASSWORD

REPORT_INTERVAL_MS   = 30000  
DISPLAY_INTERVAL_MS  = 200    
FALL_COOLDOWN_MS     = 10000  

TEMP_KEY    = "tmp"         
HUMI_KEY    = "hum"         
LIGHT_KEY   = "light"       
ACC_XYZ_KEY = "xyz"         
R_DIST_KEY  = "ycj_tof"     
L_DIST_KEY  = "zcj_tof"     
STATE_KEY   = "helmet_state"
STRUCT_KEY  = "location"    # 对应 OneNET 物模型结构体标识符

TOPIC_POST = f'$sys/{USERNAME}/{CLIENT_ID}/thing/property/post'.encode('utf-8')
TOPIC_REPLY = f'$sys/{USERNAME}/{CLIENT_ID}/thing/property/post/reply'.encode('utf-8')

# ==================== 屏幕初始化 ====================
spi = machine.SPI(1, baudrate=10000000, polarity=0, phase=0)
lcd = LCD(spi, dc_pin='F12', cs_pin='D14')
lcd.set_rotation(0)  
lcd.fill_screen(lcd.BLACK)

ldr = machine.ADC(machine.Pin('C5'))
GL5528_TABLE = [
    (40000, 1),   (26350, 2),   (20640, 3),   (17360, 4),   (15170, 5),
    (13590, 6),   (12390, 7),   (11430, 8),   (10650, 9),   (9990, 10),
    (9440, 11),   (8950, 12),   (8530, 13),   (8160, 14),   (7830, 15),
    (5000, 30),   (3500, 60),   (2500, 100),  (1500, 200),  (1000, 350),
    (750, 500),   (500, 750),   (350, 1000)
]

def get_lux_from_resistance(ohm):
    if ohm >= GL5528_TABLE[0][0]:
        return 1
    if ohm <= GL5528_TABLE[-1][0]:
        return 1000
    for i in range(len(GL5528_TABLE) - 1):
        if GL5528_TABLE[i][0] >= ohm > GL5528_TABLE[i+1][0]:
            return GL5528_TABLE[i][1]
    return 500

# ==================== 外设传感器初始化 ====================
aht20 = None
lis2dh = None
tof_left = None
tof_right = None
i2c_board = None

try:
    i2c_board = machine.I2C(1, freq=100000)
    try:
        aht20 = AHT20(i2c_board)
        print("AHT20 初始化成功！")
    except Exception as e:
        print(f"AHT20 初始化失败: {e}")

    try:
        lis2dh = LIS2DH12(i2c_board)
        print("LIS2DH12 初始化成功！")
    except Exception as e:
        print(f"LIS2DH12 初始化失败: {e}")

    try:
        tof_left = VL53L1X(i2c_board)
        if hasattr(tof_left, 'start_ranging'):
            tof_left.start_ranging()
        print("左侧 TOF 初始化成功！")
    except Exception as e:
        print(f"左侧 TOF 启动失败: {e}")

    try:
        i2c_b = machine.SoftI2C(scl=machine.Pin('F1'), sda=machine.Pin('F0'), freq=20000)
        tof_right = VL53L1X(i2c_b)
        if hasattr(tof_right, 'start_ranging'):
            tof_right.start_ranging()
        print("右侧 TOF 初始化成功！")
    except Exception as e:
        print(f"右侧 TOF 启动失败: {e}")
except Exception as e:
    print(f"硬件总线初始化异常: {e}")

fall_flag = 0         
warning_state = 0       
last_tilt_state = 0      
status_str = "NORM"      
flow_step = 0           
last_applied_status = "" 
has_spoken_connected = False  
last_valid_acc = (0.0, 0.0, 9.8)

def update_helmet_lights(status):
    global flow_step, last_applied_status
    if status in ["NORM", "WARN"] and status == last_applied_status:
        return
    last_applied_status = status

    if status == "FALL!!":
        if (time.ticks_ms() // 200) % 2 == 0:
            strip_left.set_all(*C_RED)
            strip_right.set_all(*C_RED)
        else:
            strip_left.set_all(*C_OFF)
            strip_right.set_all(*C_OFF)
    elif status == "WARN":
        strip_left.set_all(*C_YELLOW)
        strip_right.set_all(*C_YELLOW)
    elif status == "TILT-L":
        strip_right.set_all(*C_WHITE)
        strip_left.set_all(*C_OFF)
        strip_left.set_pixel(flow_step % 8, *C_YELLOW)
        strip_left.set_pixel((flow_step + 1) % 8, *C_YELLOW)
        flow_step = (flow_step + 1) % 8
    elif status == "TILT-R":
        strip_left.set_all(*C_WHITE)
        strip_right.set_all(*C_OFF)
        strip_right.set_pixel(flow_step % 8, *C_YELLOW)
        strip_right.set_pixel((flow_step + 1) % 8, *C_YELLOW)
        flow_step = (flow_step + 1) % 8
    else:
        strip_left.set_all(*C_GREEN)
        strip_right.set_all(*C_GREEN)

    strip_left.show()
    strip_right.show()

def update_display_and_read():
    global fall_flag, warning_state, last_tilt_state, status_str, last_valid_acc, lis2dh

    adc_raw = ldr.read_u16()                 
    voltage = (adc_raw / 65535.0) * 3.3          
    voltage = 3.3 - voltage
    if voltage < 0.01:
        voltage = 0.01
        
    light_lux = 10                                 
    try:
        if voltage > 0.05:
            photo_resistor = (3.3 * 10000.0 / voltage) - 10000.0
            if photo_resistor < 0:
                photo_resistor = 0
            base_lux = get_lux_from_resistance(int(photo_resistor))
            light_lux = int(base_lux * 8)
        else:
            light_lux = 10000              
    except Exception:
        light_lux = 400

    temp, humi = 25.0, 50.0
    acc_x, acc_y, acc_z = last_valid_acc

    if aht20:
        try:
            temp, humi = aht20.temperature, aht20.relative_humidity
        except Exception:
            pass

    if lis2dh:
        try:
            raw_acc = lis2dh.acceleration
            if raw_acc and (abs(raw_acc[0]) > 0.001 or abs(raw_acc[1]) > 0.001 or abs(raw_acc[2]) > 0.001):
                acc_x, acc_y, acc_z = raw_acc[2], raw_acc[1], raw_acc[0]
                last_valid_acc = (acc_x, acc_y, acc_z)
        except Exception:
            pass

    zcj_tof_val, ycj_tof_val = 0.0, 0.0
    if tof_left:
        try:
            val = tof_left.read()  
            if isinstance(val, (int, float)) and val > 0:
                zcj_tof_val = round(val / 1000.0, 2)  
        except Exception:
            pass

    if tof_right:
        try:
            val = tof_right.read()  
            if isinstance(val, (int, float)) and val > 0:
                ycj_tof_val = round(val / 1000.0, 2)  
        except Exception:
            pass

    l_dist, r_dist = zcj_tof_val, ycj_tof_val
    acc_total = math.sqrt(acc_x**2 + acc_y**2 + acc_z**2)
    
    if 0.1 < acc_total < 3.0:                     
        is_impact = (acc_total > 2.2) or (acc_total < 0.2)
        is_tilted = (abs(acc_z) < 0.4) and (abs(acc_x) > 0.7 or abs(acc_y) > 0.7)
        tilt_l_threshold, tilt_r_threshold = -0.3, 0.3
        deadzone = 0.15
    elif acc_total >= 3.0:                        
        is_impact = (acc_total > 22.0) or (acc_total < 2.0)
        is_tilted = (abs(acc_z) < 4.0) and (abs(acc_x) > 6.0 or abs(acc_y) > 6.0)
        tilt_l_threshold, tilt_r_threshold = -3.5, 3.5
        deadzone = 1.5
    else:                                         
        is_impact, is_tilted = False, False
        tilt_l_threshold, tilt_r_threshold = -3.5, 3.5
        deadzone = 1.5

    if is_tilted or is_impact:
        if fall_flag == 0:
            fall_flag = 1
            print(f"【告警】检测到跌倒！(Total Acc: {acc_total:.2f})")

    if (0 < l_dist <= 1.0) or (0 < r_dist <= 1.0):  
        if warning_state == 0:
            warning_state = 1
            print("【预警】障碍物靠近盲区（1米内）！")
    else:
        warning_state = 0

    current_tilt = last_tilt_state
    if acc_y > tilt_r_threshold:
        current_tilt = 2    
    elif acc_y < tilt_l_threshold:
        current_tilt = 1    
    elif abs(acc_y) < deadzone:
        current_tilt = 0    

    if current_tilt != last_tilt_state:
        last_tilt_state = current_tilt

    if fall_flag == 1:
        status_str, status_color = "FALL!!", lcd.RED
    elif warning_state == 1:
        status_str, status_color = "WARN", lcd.RED
    elif last_tilt_state == 1:
        status_str, status_color = "TILT-L", lcd.BLUE
    elif last_tilt_state == 2:
        status_str, status_color = "TILT-R", lcd.BLUE
    else:
        status_str, status_color = "NORM", lcd.GREEN

    # 屏幕输出（保持您原有的精细布局，并在 State 下方追加经纬度）
    lcd.show_string(0, 0,   "Light:", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(56, 0,  f"{light_lux}Lux", lcd.YELLOW, lcd.BLACK, 16)
    lcd.show_string(0, 16,  "Temp:", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(48, 16, f"{temp:.1f}C", lcd.YELLOW, lcd.BLACK, 16)
    lcd.show_string(0, 32,  "Humi:", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(48, 32, f"{humi:.1f}%", lcd.YELLOW, lcd.BLACK, 16)
    lcd.show_string(0, 48,  "G-Sensor:", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(0, 64,  f"X:{acc_x:.1f} Y:{acc_y:.1f}", lcd.YELLOW, lcd.BLACK, 16)
    lcd.show_string(0, 80,  f"Z:{acc_z:.1f}", lcd.YELLOW, lcd.BLACK, 16)
    lcd.show_string(0, 96,  "Distance:", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(0, 112, f"L:{l_dist}m R:{r_dist}m", lcd.YELLOW, lcd.BLACK, 16)
    lcd.show_string(0, 128, "Status:", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(64, 128, f"{status_str}  ", status_color, lcd.BLACK, 16)

    # 在 Status 下方顺延增加经纬度实时显示
    lat_str = f"{gnss_data['lat']:.2f}{gnss_data['lat_dir']}" if gnss_data['fixed'] else "Unfixed"
    lon_str = f"{gnss_data['lon']:.2f}{gnss_data['lon_dir']}" if gnss_data['fixed'] else "GPS..."
    lcd.show_string(0, 144, f"Lat:{lat_str}", lcd.CYAN, lcd.BLACK, 16)
    lcd.show_string(0, 160, f"Lon:{lon_str}", lcd.CYAN, lcd.BLACK, 16)

    lcd.flush()

    update_helmet_lights(status_str)

    return {
        "temp": temp, "humi": humi, "light": light_lux,
        "acc_x": round(acc_x, 2), "acc_y": round(acc_y, 2), "acc_z": round(acc_z, 2),
        "zcj_tof": l_dist, "ycj_tof": r_dist,
        "status": status_str, "fall": fall_flag,
        "gnss": gnss_data.copy()
    }

def on_message(topic, msg):
    print(f"[云端响应] Topic: {topic.decode()} | Payload: {msg.decode()}")

def connect_mqtt():
    client = MQTTClient(CLIENT_ID, BROKER, PORT, USERNAME, PASSWORD, keepalive=60)
    client.set_callback(on_message)
    client.connect()
    if hasattr(client, "sock") and client.sock:
        client.sock.setblocking(False)
    client.subscribe(TOPIC_REPLY)
    print("连接 OneNET 成功！")
    return client

client = None
last_report_ticks = time.ticks_ms()
last_display_ticks = time.ticks_ms()
last_fall_report_ticks = 0
latest_sensor_data = {}

print("启动融合定位与云端上报的智能头盔主程序...")

while True:
    try:
        if client is None:
            print("正在等待网络稳定并尝试连接 OneNET...")
            time.sleep(4)
            
            retry_count = 3
            for i in range(retry_count):
                try:
                    client = connect_mqtt()
                    break
                except Exception as conn_err:
                    print(f"第 {i+1} 次连接失败 ({conn_err})，2秒后重试...")
                    time.sleep(2)
                    if i == retry_count - 1:
                        raise conn_err

            last_report_ticks = time.ticks_ms()
            if not has_spoken_connected:
                speak_cloud_connected()
                has_spoken_connected = True

        try:
            client.check_msg()
        except Exception:
            pass

        now_ticks = time.ticks_ms()

        if time.ticks_diff(now_ticks, last_display_ticks) >= DISPLAY_INTERVAL_MS:
            last_display_ticks = now_ticks
            latest_sensor_data = update_display_and_read()

        is_fall_detected = (latest_sensor_data.get("fall") == 1)
        is_fall_cooldown_pass = time.ticks_diff(now_ticks, last_fall_report_ticks) >= FALL_COOLDOWN_MS
        is_fall_urgent = is_fall_detected and is_fall_cooldown_pass
        is_timer_due = (time.ticks_diff(now_ticks, last_report_ticks) >= REPORT_INTERVAL_MS)

        if latest_sensor_data and (is_timer_due or is_fall_urgent):
            last_report_ticks = now_ticks
            msg_id = str(urandom.getrandbits(16) + 1000)

            g_info = latest_sensor_data.get("gnss", {})
            
            payload = {
                "id": msg_id,
                "version": "1.0",
                "params": {
                    TEMP_KEY:    {"value": round(latest_sensor_data["temp"], 1)},
                    HUMI_KEY:    {"value": round(latest_sensor_data["humi"], 1)},
                    LIGHT_KEY:   {"value": int(latest_sensor_data["light"])},
                    ACC_XYZ_KEY: {
                        "value": {
                            "x": latest_sensor_data["acc_x"],
                            "y": latest_sensor_data["acc_y"],
                            "z": latest_sensor_data["acc_z"]
                        }
                    },
                    L_DIST_KEY:  {"value": float(latest_sensor_data["zcj_tof"])},
                    R_DIST_KEY:  {"value": float(latest_sensor_data["ycj_tof"])},
                    STATE_KEY:   {"value": latest_sensor_data["status"]},
                    STRUCT_KEY:  {
                        "value": {
                            "lat": g_info.get("lat", 0.0),
                            "lat_dir": g_info.get("lat_dir", "N"),
                            "lon": g_info.get("lon", 0.0),
                            "lon_dir": g_info.get("lon_dir", "E"),
                            "alt": g_info.get("alt", 0.0),
                            "speed": g_info.get("speed", 0.0)
                        }
                    }
                }
            }

            data_post = json.dumps(payload)
            if is_fall_urgent:
                last_fall_report_ticks = now_ticks
                print("【紧急上报】检测到跌倒及定位，发送告警！")
                fall_flag = 0  
            else:
                print("触发周期上报，发送传感器与定位数据到 OneNET...")

            try:
                client.publish(TOPIC_POST, data_post)
                print("数据成功发送至 OneNET 云端！")
            except Exception as pub_err:
                print(f"发送数据卡顿或超时: {pub_err}，主动重置连接...")
                if client:
                    try:
                        if hasattr(client, 'sock') and client.sock:
                            client.sock.close()
                        client.disconnect()
                    except Exception:
                        pass
                    client = None
                raise pub_err

            led_status = 1 - led_status
            led_red.value(led_status)

        time.sleep_ms(30)

    except Exception as e:
        print(f"运行异常: {repr(e)}，正在重置网络通道并在 3 秒后重连...")
        if client:
            try:
                if hasattr(client, 'sock') and client.sock:
                    client.sock.close()
                client.disconnect()
            except Exception:
                pass
            client = None
        time.sleep(3)