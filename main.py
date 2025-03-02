import os
from collections import namedtuple
from datetime import datetime
from functools import partial
from typing import Optional

import requests
from PyQt5.QtCore import QTimer
from loguru import logger

from .ClassWidgets.base import PluginBase

# 天气状态映射表
WEATHER_STATUS = {
    0: "晴", 1: "多云", 2: "阴", 3: "阵雨", 4: "雷阵雨",
    5: "雷阵雨并伴有冰雹", 6: "雨夹雪", 7: "小雨", 8: "中雨",
    9: "大雨", 10: "暴雨", 11: "大暴雨", 12: "特大暴雨", 13: "阵雪",
    14: "小雪", 15: "中雪", 16: "大雪", 17: "暴雪", 18: "雾",
    19: "冻雨", 20: "沙尘暴", 21: "小雨-中雨", 22: "中雨-大雨",
    23: "大雨-暴雨", 24: "暴雨-大暴雨", 25: "大暴雨-特大暴雨",
    26: "小雪-中雪", 27: "中雪-大雪", 28: "大雪-暴雪", 29: "浮沉",
    30: "扬沙", 31: "强沙尘暴", 32: "飑", 33: "龙卷风",
    34: "若高吹雪", 35: "轻雾", 53: "霾", 99: "未知"
}

WeatherData = namedtuple('WeatherData',
                         ['daily_temp', 'daily_precip', 'hourly_weather', 'alerts'])


def get_weather_description(code: int) -> str:
    """根据天气代码获取天气描述"""
    return WEATHER_STATUS.get(code, "未知")


def parse_weather(data) -> Optional[WeatherData]:
    """解析天气数据，返回结构化对象, 并包含预警信息"""

    def get_daily_entries(values, template):
        """生成每日数据条目"""
        return [template.format(v['from'], v['to']) if i < len(values) else "N/A"
                for i, v in enumerate(values[:3])]

    def get_hourly_entries(temp_values, code_values):
        """生成小时数据条目"""
        return [
            f"{get_weather_description(code)} {temp}℃"
            if i < len(temp_values) and i < len(code_values)
            else "N/A"
            for i, (temp, code) in enumerate(zip(temp_values[:3], code_values[:3]))
        ]

    # 日预报处理
    daily_temp = get_daily_entries(
        data.get('forecastDaily', {}).get('temperature', {}).get('value', []),
        "{}℃~{}℃"
    )

    daily_precip = [
        f"{v}%" if i < len(
            data.get('forecastDaily', {}).get('precipitationProbability', {}).get('value', [])) else "N/A"
        for i, v in enumerate(data.get('forecastDaily', {}).get('precipitationProbability', {}).get('value', [])[:3])
    ]

    # 小时预报处理
    hourly_temp = data.get('forecastHourly', {}).get('temperature', {}).get('value', [])
    hourly_codes = data.get('forecastHourly', {}).get('weather', {}).get('value', [])
    hourly_weather = get_hourly_entries(hourly_temp, hourly_codes)

    # 预警信息处理
    alerts = data.get('alerts', [])  # 获取预警信息，默认为空列表

    return WeatherData(
        " | ".join(daily_temp),
        " | ".join(daily_precip),
        " | ".join(hourly_weather),
        alerts
    )


class Plugin(PluginBase):
    def __init__(self, cw_contexts, method):
        super().__init__(cw_contexts, method)
        self.plugin_dir = cw_contexts['PLUGIN_PATH']
        self.notified_times = set()
        self.current_date = datetime.now().date()
        self.weather_data: Optional[WeatherData] = None
        self.cache_dir = os.path.join(self.plugin_dir, 'cache')  # 定义缓存目录

        # 确保缓存目录存在
        os.makedirs(self.cache_dir, exist_ok=True)

    def update(self, cw_contexts):
        super().update(cw_contexts)
        now = datetime.now()
        current_time = now.strftime('%H:%M:%S')  # 添加秒级精度

        # 日期变更检测（自动重置记录）
        if now.date() != self.current_date:
            self.notified_times.clear()
            self.current_date = now.date()

        # 数据校验
        if cw_contexts.get('Weather_API') != 'xiaomi_weather':
            return
        if not (weather_data := cw_contexts.get('Weather_Data')):
            return

        # 数据处理
        self.weather_data = parse_weather(weather_data)

        # 触发通知时间点
        trigger_times = {'09:38:00', '12:00:45', '14:30:30', '17:50:45', '19:40:30'}

        if current_time in trigger_times and current_time not in self.notified_times:
            self._schedule_notifications()
            self.notified_times.add(current_time)

    def _schedule_notifications(self):
        """智能调度天气预报通知，包含预警信息"""
        notifications = []
        current_delay = 0  # 初始化延时为 0
        weather_notification_duration = 5000  # 默认天气预报通知持续时间
        max_delay = 0  # 初始化最大延迟时间

        # 添加天气预报通知
        notifications.append((current_delay, '天气预报', '', weather_notification_duration))
        current_delay += weather_notification_duration  # 延时增加天气预报通知持续时间
        max_delay = max(max_delay, current_delay)  # 更新最大延迟时间

        # 添加天气预警通知 (如果有)
        if self.weather_data and self.weather_data.alerts:  # 检查 weather_data 和 alerts 是否存在
            alert = self.weather_data.alerts[0]  # 假设只取第一个预警信息
            icon_url = alert['images']['icon']
            icon_path = self._download_alert_icon(icon_url)  # 下载预警图标
            alert_detail = alert['detail']

            alert_title_part = self._split_alert_detail(alert_detail)  # 尝试拆分 detail 文本，只获取标题部分

            if alert_title_part:  # 拆分成功，获取到标题部分
                notifications.append(
                    (current_delay, '天气预警', alert_title_part, 5000, icon_path))  # 天气预警通知, 内容为标题部分, 持续 5 秒
                current_delay += 5000  # 延时增加 5 秒
                max_delay = max(max_delay, current_delay)  # 更新最大延迟时间

        notifications.extend([  # 使用 extend 一次性添加其他通知，延时从 current_delay 开始
            (current_delay, '近三天温度', getattr(self.weather_data, 'daily_temp', 'N/A'), 10000),
            (current_delay + 10000, '近三天降雨概率', getattr(self.weather_data, 'daily_precip', 'N/A'), 10000),
            (current_delay + 20000, '接下来三小时天气', getattr(self.weather_data, 'hourly_weather', 'N/A'), 10000)
        ])
        max_delay = current_delay + 20000  # 计算最后一个通知的结束时间作为最大延迟时间

        for delay, title, content, duration, *args in notifications:  # 修改循环解包，接收可变的参数
            icon = args[0] if args else None  # 从可变参数中获取 icon，如果没有则为 None
            QTimer.singleShot(delay, partial(
                self._send_notification,
                title=title,
                content=content,
                duration=duration,
                icon=icon  # 传递 icon 参数
            ))

        # 安排在所有通知发送完毕后删除缓存图标
        QTimer.singleShot(max_delay + 1000, self._delete_cached_icons)  # 延迟 max_delay + 1000ms 后执行缓存删除

    def _send_notification(self, title: str, content: str, duration: int,
                           icon: Optional[str] = None):  # 增加 icon 参数，并设置为 Optional
        """统一通知发送方法，可以发送带图标的通知"""
        # 发送通知到主线程
        self.method.send_notification(
            state=4,
            title=title,
            subtitle='',
            content=content,
            icon=icon,  # 传递 icon 参数
            duration=duration
        )

    def _download_alert_icon(self, icon_url: str) -> Optional[str]:
        """下载预警图标并保存到本地缓存目录"""
        try:
            response = requests.get(icon_url, stream=True, timeout=5)  # 设置超时时间
            response.raise_for_status()  # 检查请求是否成功

            file_extension = os.path.splitext(icon_url)[1]  # 获取文件扩展名
            if not file_extension:
                file_extension = '.webp'  # 默认使用 .webp 扩展名

            icon_filename = f"alert_icon_{hash(icon_url)}{file_extension}"  # 使用 URL hash 避免文件名冲突
            local_icon_path = os.path.join(self.cache_dir, icon_filename)

            with open(local_icon_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            return local_icon_path  # 返回本地文件路径
        except requests.exceptions.RequestException as e:
            print(f"下载预警图标失败: {e}")  # 打印错误信息
            return None  # 下载失败返回 None

    @staticmethod
    def _split_alert_detail(detail_text: str) -> Optional[str]:
        """拆分预警 detail 文本"""
        try:
            parts = detail_text.split("：", 1)  # 使用中文冒号分割一次
            if len(parts) > 0:  # 确保分割后有内容
                return parts[0].strip()  # 返回冒号前的内容，并去除前后空白
            return None  # 如果没有冒号，或者冒号后没有内容，返回 None
        except Exception:
            return None  # 拆分出现异常也返回 None

    def _delete_cached_icons(self):
        """删除缓存目录下的所有图标文件"""
        try:
            file_list = os.listdir(self.cache_dir)
            for filename in file_list:
                file_path = os.path.join(self.cache_dir, filename)
                if os.path.isfile(file_path):  # 确保是文件而不是目录
                    os.remove(file_path)
            logger.success(f"缓存图标已删除")
        except Exception as e:
            logger.error(f"删除缓存图标失败: {e}")
