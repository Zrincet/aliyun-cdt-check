#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
from datetime import datetime

# 复用主模块的公共函数
from aliyun_cdt_check import (
    load_config,
    get_region_name,
    get_traffic,
    get_security_group_id,
    is_security_group_rule_enabled,
    get_instance_details,
    validate_credentials_and_instance,
    send_email_notification,
    send_bark_notification,
    send_tg_notification,
    send_webhook_notification,
    send_qywx_notification,
)


def send_daily_notification_message(message, traffic, notification_config):
    """发送每日通知"""
    results = {}
    title = notification_config.get('title', 'CDT流量统计')

    if notification_config.get('enableEmail'):
        results['email'] = send_email_notification(message, title, notification_config)

    if notification_config.get('enableBark'):
        results['bark'] = send_bark_notification(message, notification_config['barkUrl'])

    if notification_config.get('enableTG'):
        results['tg'] = send_tg_notification(message, notification_config['tgBotToken'], notification_config['tgChatId'])

    if notification_config.get('enableWebhook'):
        daily_title = f"已使用{traffic} - {title}"
        results['webhook'] = send_webhook_notification(
            message, notification_config['webhookUrl'], daily_title, notification_config['webhookId'])

    if notification_config.get('enableQywx'):
        daily_title = f"已使用{traffic} - {title}"
        results['qywx'] = send_qywx_notification(
            message, daily_title, notification_config['touser'], notification_config['corpid'],
            notification_config['corpsecret'], notification_config['agentid'],
            notification_config['baseApiUrl'], notification_config['picUrl'])

    for key, result in results.items():
        if result is not True:
            print(f"通知发送失败: {json.dumps(results, ensure_ascii=False)}")
            return False

    print("通知发送成功")
    return True


def send_daily_notification():
    """每日通知主逻辑"""
    config = load_config()
    accounts = config['Accounts']
    notification_config = config['Notification']

    for account in accounts:
        # 检查是否启用通知
        if not account.get('enableNotification', True):
            print(f"跳过账户 {account['accountName']}：未启用通知")
            continue

        # 检查是否仅在防火墙切换时通知
        if account.get('onlyNotifyOnToggle', False):
            print(f"跳过账户 {account['accountName']}：仅在防火墙切换时通知")
            continue

        # 验证 AK/SK 和实例 ID
        if not validate_credentials_and_instance(account, notification_config):
            continue

        try:
            traffic = get_traffic(account['AccessKeyId'], account['AccessKeySecret'])
            usage_percentage = round((traffic / account['maxTraffic']) * 100, 2)

            instance_details = get_instance_details(
                account['AccessKeyId'], account['AccessKeySecret'],
                account['instanceId'], account['regionId'])

            security_group_id = get_security_group_id(
                account['instanceId'], account['AccessKeyId'],
                account['AccessKeySecret'], account['regionId'])

            is_enabled = is_security_group_rule_enabled(
                security_group_id, account['AccessKeyId'],
                account['AccessKeySecret'], account['regionId'])

            if not is_enabled:
                continue  # 安全组已禁用，不发送通知

            # 生成进度条
            progress_val = round(usage_percentage)
            progress_all_num = 20
            progress_do_text = '■'
            progress_undo_text = '□'

            if usage_percentage > 0 and usage_percentage < 1:
                progress_do_num = 1
            elif int(progress_val) == 0:
                progress_do_num = 0
            elif int(progress_val) > 95 and usage_percentage < 100:
                progress_do_num = progress_all_num - 1
            else:
                progress_do_num = min(progress_all_num, round(0.5 + (progress_all_num * int(progress_val)) / 100))

            progress_undo_num = progress_all_num - progress_do_num
            progress_bar = progress_do_text * progress_do_num + progress_undo_text * progress_undo_num

            try:
                formatted_datetime = datetime.fromisoformat(
                    instance_details['到期时间'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, AttributeError):
                formatted_datetime = instance_details['到期时间']

            message = f"{account['accountName']}（{instance_details['公网IP地址']}）\n"
            message += f"{progress_bar} {usage_percentage}%\n"
            message += f"已使用流量: {round(traffic, 2)}GB / {account['maxTraffic']}GB\n"
            message += f"实例地区: {get_region_name(account['regionId'])}\n"
            message += f"到期时间: {formatted_datetime}\n"
            message += f"实例ID: {account['instanceId']}\n"
            message += f"安全组状态: 启用\n"

            traffic_str = f"{round(traffic, 2)}GB"

            send_daily_notification_message(message, traffic_str, notification_config)

        except Exception as e:
            print(f'异常: {e}')


if __name__ == '__main__':
    send_daily_notification()
