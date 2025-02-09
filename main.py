import json
from collections import namedtuple
from datetime import datetime
from functools import partial
from typing import Optional

from PyQt5.QtCore import QTimer

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

WeatherData = namedtuple('WeatherData', ['daily_temp', 'daily_precip', 'hourly_weather'])


def get_weather_description(code: int) -> str:
    """根据天气代码获取天气描述"""
    return WEATHER_STATUS.get(code, "未知")


def parse_weather(json_data: str) -> Optional[WeatherData]:
    """解析天气数据，返回结构化对象"""
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError:
        return None

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

    return WeatherData(
        " | ".join(daily_temp),
        " | ".join(daily_precip),
        " | ".join(hourly_weather)
    )


class Plugin(PluginBase):
    def __init__(self, cw_contexts, method):
        super().__init__(cw_contexts, method)
        self.plugin_dir = cw_contexts['PLUGIN_PATH']
        self.notified_times = set()
        self.current_date = datetime.now().date()
        self.weather_data: Optional[WeatherData] = None

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
        trigger_times = {'12:00:15', '16:05:30', '20:10:30'}
        if current_time in trigger_times and current_time not in self.notified_times:
            self._schedule_notifications()
            self.notified_times.add(current_time)

    def _schedule_notifications(self):
        """智能调度天气预报通知"""
        notifications = [
            (0, '天气预报', '', 5000),
            (5000, '近三天温度', getattr(self.weather_data, 'daily_temp', 'N/A'), 10000),
            (15000, '近三天降雨概率', getattr(self.weather_data, 'daily_precip', 'N/A'), 10000),
            (25000, '接下来三小时天气', getattr(self.weather_data, 'hourly_weather', 'N/A'), 10000)
        ]

        for delay, title, content, duration in notifications:
            QTimer.singleShot(delay, partial(
                self._send_notification,
                title=title,
                content=content,
                duration=duration
            ))

    def _send_notification(self, title: str, content: str, duration: int):
        """统一通知发送方法"""
        self.method.send_notification(
            state=4,
            title=title,
            subtitle='',
            content=content,
            duration=duration
        )
