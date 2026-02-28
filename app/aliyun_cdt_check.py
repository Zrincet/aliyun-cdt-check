#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import quote, quote_plus

import requests
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_tea_util import models as util_models

# 区域名称映射
REGION_NAMES = {
    'cn-qingdao': '华北1(青岛)',
    'cn-beijing': '华北2(北京)',
    'cn-zhangjiakou': '华北3(张家口)',
    'cn-huhehaote': '华北5(呼和浩特)',
    'cn-wulanchabu': '华北6(乌兰察布)',
    'cn-hangzhou': '华东1(杭州)',
    'cn-shanghai': '华东2(上海)',
    'cn-nanjing': '华东5 (南京-本地地域)',
    'cn-fuzhou': '华东6(福州-本地地域)',
    'cn-wuhan-lr': '华中1(武汉-本地地域)',
    'cn-shenzhen': '华南1(深圳)',
    'cn-heyuan': '华南2(河源)',
    'cn-guangzhou': '华南3(广州)',
    'cn-chengdu': '西南1(成都)',
    'cn-hongkong': '中国香港',
    'ap-southeast-1': '新加坡',
    'ap-southeast-2': '澳大利亚(悉尼)',
    'ap-southeast-3': '马来西亚(吉隆坡)',
    'ap-southeast-5': '印度尼西亚(雅加达)',
    'ap-southeast-6': '菲律宾(马尼拉)',
    'ap-southeast-7': '泰国(曼谷)',
    'ap-northeast-1': '日本(东京)',
    'ap-northeast-2': '韩国(首尔)',
    'us-west-1': '美国(硅谷)',
    'us-east-1': '美国(弗吉尼亚)',
    'eu-central-1': '德国(法兰克福)',
    'eu-west-1': '英国(伦敦)',
    'me-east-1': '阿联酋(迪拜)',
    'me-central-1': '沙特(利雅得)',
}


def load_config():
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_region_name(region_id):
    """获取区域名称"""
    return REGION_NAMES.get(region_id, '未知地区')


def create_cdt_client(access_key_id, access_key_secret):
    """创建 CDT API 客户端"""
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint='cdt.aliyuncs.com'
    )
    return OpenApiClient(config)


def create_ecs_client(access_key_id, access_key_secret, region_id):
    """创建 ECS API 客户端"""
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint=f'ecs.{region_id}.aliyuncs.com'
    )
    return OpenApiClient(config)


def api_call(client, action, version, queries=None):
    """通用 API 调用"""
    params = open_api_models.Params(
        action=action,
        version=version,
        protocol='HTTPS',
        method='POST',
        auth_type='AK',
        style='RPC',
        pathname='/',
        req_body_type='json',
        body_type='json',
    )
    request = open_api_models.OpenApiRequest(query=queries or {})
    runtime = util_models.RuntimeOptions()
    result = client.call_api(params, request, runtime)
    return result.get('body', {})


def get_traffic(access_key_id, access_key_secret):
    """获取 CDT 流量使用量（GB）"""
    try:
        client = create_cdt_client(access_key_id, access_key_secret)
        result = api_call(client, 'ListCdtInternetTraffic', '2021-08-13')
        traffic_details = result.get('TrafficDetails', [])
        total = sum(item.get('Traffic', 0) for item in traffic_details)
        return total / (1024 * 1024 * 1024)  # 转换为 GB
    except Exception as e:
        print(f'获取流量异常: {e}')
        return 0


def get_security_group_id(instance_id, access_key_id, access_key_secret, region_id):
    """获取实例的安全组 ID"""
    try:
        client = create_ecs_client(access_key_id, access_key_secret, region_id)
        result = api_call(client, 'DescribeInstanceAttribute', '2014-05-26', {
            'RegionId': region_id,
            'InstanceId': instance_id,
        })
        return result['SecurityGroupIds']['SecurityGroupId'][0]
    except Exception as e:
        print(f'获取安全组ID异常: {e}')
        return None


def is_security_group_rule_enabled(security_group_id, access_key_id, access_key_secret, region_id):
    """检查安全组中是否存在 0.0.0.0/0 入站规则"""
    try:
        client = create_ecs_client(access_key_id, access_key_secret, region_id)
        result = api_call(client, 'DescribeSecurityGroupAttribute', '2014-05-26', {
            'RegionId': region_id,
            'SecurityGroupId': security_group_id,
        })
        permissions = result.get('Permissions', {}).get('Permission', [])
        for rule in permissions:
            if (rule.get('IpProtocol', '').upper() == 'ALL'
                    and rule.get('SourceCidrIp') == '0.0.0.0/0'
                    and rule.get('Policy') == 'Accept'
                    and rule.get('NicType') == 'intranet'
                    and rule.get('Direction') == 'ingress'):
                return True
        return False
    except Exception as e:
        print(f'检查安全组规则异常: {e}')
        return False


def disable_security_group_rule(security_group_id, access_key_id, access_key_secret, region_id):
    """禁用安全组中 0.0.0.0/0 的入站规则"""
    try:
        client = create_ecs_client(access_key_id, access_key_secret, region_id)
        api_call(client, 'RevokeSecurityGroup', '2014-05-26', {
            'RegionId': region_id,
            'SecurityGroupId': security_group_id,
            'IpProtocol': 'all',
            'PortRange': '-1/-1',
            'SourceCidrIp': '0.0.0.0/0',
        })
        print('已禁用0.0.0.0/0的全部协议规则')
    except Exception as e:
        print(f'禁用安全组规则异常: {e}')


def enable_security_group_rule(security_group_id, access_key_id, access_key_secret, region_id):
    """恢复安全组中 0.0.0.0/0 的入站规则"""
    try:
        client = create_ecs_client(access_key_id, access_key_secret, region_id)
        api_call(client, 'AuthorizeSecurityGroup', '2014-05-26', {
            'RegionId': region_id,
            'SecurityGroupId': security_group_id,
            'IpProtocol': 'all',
            'PortRange': '-1/-1',
            'SourceCidrIp': '0.0.0.0/0',
        })
        print('已恢复0.0.0.0/0的全部协议规则')
    except Exception as e:
        print(f'恢复安全组规则异常: {e}')


def validate_credentials_and_instance(account, notification_config):
    """验证 AK/SK 和实例 ID 是否有效"""
    try:
        client = create_ecs_client(account['AccessKeyId'], account['AccessKeySecret'], account['regionId'])
        result = api_call(client, 'DescribeInstances', '2014-05-26', {
            'RegionId': account['regionId'],
        })
        instances = result.get('Instances', {}).get('Instance', [])
        instance_valid = any(inst['InstanceId'] == account['instanceId'] for inst in instances)
        if not instance_valid:
            raise Exception(f"指定的实例ID不存在: {account['instanceId']}")
        return True
    except Exception as e:
        print(f"验证异常: {e}")
        log = {
            '服务器': account.get('accountName', ''),
            '实例ID': account.get('instanceId', ''),
            '错误信息': str(e),
        }
        send_notification(log, notification_config)
        return False


def get_instance_details(access_key_id, access_key_secret, instance_id, region_id):
    """获取实例详细信息（到期时间、公网 IP）"""
    try:
        client = create_ecs_client(access_key_id, access_key_secret, region_id)
        result = api_call(client, 'DescribeInstances', '2014-05-26', {
            'RegionId': region_id,
            'InstanceIds': json.dumps([instance_id]),
        })
        instances = result.get('Instances', {}).get('Instance', [])
        if instances:
            instance = instances[0]
            expiration_time = instance.get('ExpiredTime', '无到期时间')
            public_ip = '无公网 IP 地址'
            eip = instance.get('EipAddress', {}).get('IpAddress')
            if eip:
                public_ip = eip
            return {'到期时间': expiration_time, '公网IP地址': public_ip}
        return {'到期时间': '无到期时间', '公网IP地址': '无公网 IP 地址'}
    except Exception as e:
        print(f'获取实例详情异常: {e}')
        return {'到期时间': '查询失败', '公网IP地址': '查询失败'}


def send_notification(log, notification_config):
    """发送通知"""
    # 组装通知内容
    if '错误信息' in log:
        message = f"⚠️ 错误通知\n"
        message += f"服务器: {log.get('服务器', '')}\n"
        message += f"错误信息: {log['错误信息']}\n"
        if '实例ID' in log:
            message += f"实例ID: {log['实例ID']}\n"
    else:
        message = f"服务器: {log['服务器']}\n"
        message += f"实例ID: {log['实例ID']}\n"
        message += f"实例IP: {log['公网IP地址']}\n"
        message += f"到期时间: {log['实例到期时间']}\n"
        message += f"CDT总流量: {log['总流量']}\n"
        message += f"已使用流量: {log['已使用流量']}\n"
        message += f"使用百分比: {log['使用百分比']}\n"
        message += f"地区: {log['地区']}\n"
        message += f"安全组状态: {log['安全组状态']}\n"

    results = {}
    title = notification_config.get('title', 'CDT流量统计')

    if notification_config.get('enableEmail'):
        results['email'] = send_email_notification(message, title, notification_config)

    if notification_config.get('enableBark'):
        results['bark'] = send_bark_notification(message, notification_config['barkUrl'])

    if notification_config.get('enableTG'):
        results['tg'] = send_tg_notification(message, notification_config['tgBotToken'], notification_config['tgChatId'])

    if notification_config.get('enableWebhook'):
        results['webhook'] = send_webhook_notification(
            message, notification_config['webhookUrl'], title, notification_config['webhookId'])

    if notification_config.get('enableQywx'):
        results['qywx'] = send_qywx_notification(
            message, title, notification_config['touser'], notification_config['corpid'],
            notification_config['corpsecret'], notification_config['agentid'],
            notification_config['baseApiUrl'], notification_config['picUrl'])

    for key, result in results.items():
        if result is not True:
            return f"发送失败: {json.dumps(results, ensure_ascii=False)}"
    return True


def send_email_notification(message, title, config):
    """发送邮件通知"""
    try:
        msg = MIMEMultipart()
        msg['From'] = config['username']
        msg['To'] = config['email']
        msg['Subject'] = title
        html_body = message.replace('\n', '<br>')
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        if config.get('secure') == 'tls':
            server = smtplib.SMTP(config['host'], config['port'])
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(config['host'], config['port'])
        server.login(config['username'], config['password'])
        server.sendmail(config['username'], config['email'], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'邮件发送失败: {e}')
        return str(e)


def send_bark_notification(message, bark_url):
    """发送 Bark 通知"""
    try:
        full_url = f"{bark_url}/流量告警/{quote(message)}"
        resp = requests.get(full_url, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f'Bark 通知失败: {e}')
        return False


def send_tg_notification(message, bot_token, chat_id):
    """发送 Telegram 通知"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.get(url, params={'chat_id': chat_id, 'text': message}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f'Telegram 通知失败: {e}')
        return False


def send_webhook_notification(message, webhook_url, title, webhook_id):
    """发送 Webhook 通知"""
    try:
        full_url = f"{webhook_url}&id={webhook_id}&title={quote(title)}&content={quote_plus(message)}"
        resp = requests.get(full_url, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f'Webhook 通知失败: {e}')
        return False


def send_qywx_notification(message, title, touser, corpid, corpsecret, agentid, base_api_url, pic_url):
    """发送企业微信通知"""
    try:
        # 获取 access_token
        token_url = f"{base_api_url}/cgi-bin/gettoken?corpid={corpid}&corpsecret={corpsecret}"
        resp = requests.get(token_url, timeout=10, verify=False)
        token_data = resp.json()
        access_token = token_data['access_token']

        # 发送消息
        send_url = f"{base_api_url}/cgi-bin/message/send?access_token={access_token}"
        postdata = {
            'touser': touser,
            'msgtype': 'news',
            'agentid': agentid,
            'news': {
                'articles': [{
                    'title': title,
                    'description': message,
                    'url': '',
                    'picurl': pic_url,
                }]
            },
            'enable_id_trans': 0,
            'enable_duplicate_check': 0,
            'duplicate_check_interval': 1800,
        }
        resp = requests.post(send_url, json=postdata, timeout=10, verify=False)
        response = resp.json()
        return response.get('errcode') == 0
    except Exception as e:
        print(f'企业微信通知失败: {e}')
        return False


def check():
    """主检测逻辑"""
    config = load_config()
    accounts = config['Accounts']
    notification_config = config['Notification']
    logs = []

    for account in accounts:
        # 验证 AK/SK 和实例 ID
        if not validate_credentials_and_instance(account, notification_config):
            continue

        try:
            traffic = get_traffic(account['AccessKeyId'], account['AccessKeySecret'])
            account_name = account.get('accountName', account['AccessKeyId'][:7] + '***')
            usage_percentage = round((traffic / account['maxTraffic']) * 100, 2)
            region_name = get_region_name(account['regionId'])

            security_group_id = get_security_group_id(
                account['instanceId'], account['AccessKeyId'], account['AccessKeySecret'], account['regionId'])

            instance_details = get_instance_details(
                account['AccessKeyId'], account['AccessKeySecret'], account['instanceId'], account['regionId'])

            log = {
                '实例ID': account['instanceId'],
                '服务器': account_name,
                '总流量': f"{account['maxTraffic']}GB",
                '已使用流量': f"{round(traffic, 2)}GB",
                '使用百分比': f"{usage_percentage}%",
                '地区': region_name,
                '实例到期时间': instance_details['到期时间'],
                '公网IP地址': instance_details['公网IP地址'],
                '使用率达到95%': '是' if usage_percentage >= 95 else '否',
            }

            is_enabled = is_security_group_rule_enabled(
                security_group_id, account['AccessKeyId'], account['AccessKeySecret'], account['regionId'])

            if usage_percentage >= 95:
                if is_enabled:
                    disable_security_group_rule(
                        security_group_id, account['AccessKeyId'], account['AccessKeySecret'], account['regionId'])
                    log['安全组状态'] = '已禁用 0.0.0.0/0 访问规则'
                    notification_result = send_notification(log, notification_config)
                    log['通知发送'] = '成功' if notification_result is True else f"失败: {notification_result}"
                else:
                    log['安全组状态'] = '规则已禁用，无需操作'
                    log['通知发送'] = '不需要'
            else:
                if not is_enabled:
                    enable_security_group_rule(
                        security_group_id, account['AccessKeyId'], account['AccessKeySecret'], account['regionId'])
                    log['安全组状态'] = '已恢复 0.0.0.0 访问规则'
                    notification_result = send_notification(log, notification_config)
                    log['通知发送'] = '成功' if notification_result is True else f"失败: {notification_result}"
                else:
                    log['安全组状态'] = '规则已启用，无需操作'
                    log['通知发送'] = '不需要'

            logs.append(log)
        except Exception as e:
            print(f'异常: {e}')
            error_log = {
                '服务器': account_name,
                '实例ID': account.get('instanceId', ''),
                '错误信息': str(e),
            }
            send_notification(error_log, notification_config)

    write_log(logs)


def write_log(logs):
    """写入日志"""
    data = {
        '获取时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '日志': logs,
    }
    json_data = json.dumps(data, ensure_ascii=False, indent=4)
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(json_data)
    print(json_data)


if __name__ == '__main__':
    check()
