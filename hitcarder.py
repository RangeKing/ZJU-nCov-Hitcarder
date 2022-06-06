# -*- coding: utf-8 -*-
import requests
from requests.adapters import HTTPAdapter
try:
    from requests.packages.urllib3.util.retry import Retry
    from urllib2 import URLError
except ImportError:
    from urllib3.util import Retry
    from urllib.error import URLError
import json
import re
import time
import datetime
import os
import sys
import message
import base64


def ocr_api(image_base64, API_KEY, SECRET_KEY):
    '''
    调用百度云OCR API进行验证码识别
    '''
    request_url = 'https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic'  # 使用通用文字识别（标准版）
    host = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={API_KEY}&client_secret={SECRET_KEY}'

    if response := requests.get(host):
        access_token = response.json()['access_token']
    params = {"image": image_base64}
    request_url = f"{request_url}?access_token={access_token}"
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    if response := requests.post(request_url, data=params, headers=headers):
        return response.json()


class HitCarder(object):
    """Hit carder class

    Attributes:
        username: (str) 浙大统一认证平台用户名（一般为学号）
        password: (str) 浙大统一认证平台密码
        API_KEY: (str) 百度智能云 API_KEY
        SECRET_KEY: (str) 百度智能云 SECRET_KEY
        login_url: (str) 登录url
        base_url: (str) 打卡首页url
        save_url: (str) 提交打卡url
        sess: (requests.Session) 统一的session
    """

    def __init__(self, username, password, API_KEY, SECRET_KEY):
        self.username = username
        self.password = password
        self.API_KEY = API_KEY
        self.SECRET_KEY = SECRET_KEY
        self.login_url = "https://zjuam.zju.edu.cn/cas/login?service=https%3A%2F%2Fhealthreport.zju.edu.cn%2Fa_zju%2Fapi%2Fsso%2Findex%3Fredirect%3Dhttps%253A%252F%252Fhealthreport.zju.edu.cn%252Fncov%252Fwap%252Fdefault%252Findex"
        self.base_url = "https://healthreport.zju.edu.cn/ncov/wap/default/index"
        self.save_url = "https://healthreport.zju.edu.cn/ncov/wap/default/save"
        self.code_url = "https://healthreport.zju.edu.cn/ncov/wap/default/code"
        self.sess = requests.Session()
        self.sess.keep_alive = False
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.sess.mount('http://', adapter)
        self.sess.mount('https://', adapter)
        # ua = UserAgent()
        # self.sess.headers['User-Agent'] = ua.chrome
        self.sess.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'}

    def login(self):
        """Login to ZJU platform"""
        time.sleep(1)
        res = self.sess.get(self.login_url)
        execution = re.search('name="execution" value="(.*?)"', res.text)[1]

        time.sleep(1)
        res = self.sess.get(
            url='https://zjuam.zju.edu.cn/cas/v2/getPubKey').json()
        n, e = res['modulus'], res['exponent']
        encrypt_password = self._rsa_encrypt(self.password, e, n)

        data = {
            'username': self.username,
            'password': encrypt_password,
            'execution': execution,
            '_eventId': 'submit'
        }
        time.sleep(1)
        res = self.sess.post(url=self.login_url, data=data)

        # check if login successfully
        if '统一身份认证' in res.content.decode():
            raise LoginError('登录失败，请核实账号密码重新登录')
        return self.sess

    def post(self):
        """Post the hit card info."""
        time.sleep(1)
        res = self.sess.post(self.save_url, data=self.info)
        return json.loads(res.text)

    def get_date(self):
        """Get current date."""
        today = datetime.datetime.now(
            datetime.timezone.utc) + datetime.timedelta(hours=+8)

        return "%4d%02d%02d" % (today.year, today.month, today.day)

    def check_form(self):
        """Get hitcard form, compare with old form """
        res = self.sess.get(self.base_url)
        html = res.content.decode()

        try:
            new_form = re.findall(r'<ul>[\s\S]*?</ul>', html)[0]
        except IndexError as _:
            raise RegexMatchError(
                'Relative info not found in html with regex') from _

        with open("form.txt", "r", encoding="utf-8") as f:
            if new_form == f.read():
                return True
        # with open("form.txt", "w", encoding="utf-8") as f:
        #     f.write(new_form)
        return False

    def get_verify_code(self):
        """Get verify code"""
        res = self.sess.get(self.code_url)
        code_base64 = base64.b64encode(res.content)
        try:
            verify_code = ocr_api(code_base64, self.API_KEY, self.SECRET_KEY)[
                'words_result'][0]['words']
        except URLError as err:
            print(err)
        return verify_code

    def get_info(self, html=None):
        """Get hit card info, which is the old info with updated new time."""
        if not html:
            time.sleep(1)
            res = self.sess.get(self.base_url)
            html = res.content.decode()

        try:
            old_infos = re.findall(r'oldInfo: ({[^\n]+})', html)
            if len(old_infos) != 0:
                old_info = json.loads(old_infos[0])
            else:
                raise RegexMatchError("未发现缓存信息，请先至少手动成功打卡一次再运行脚本")

            def_info = json.loads(re.findall(r'def = ({[^\n]+})', html)[0])
            magic_code = re.findall(
                r'"([0-9a-z]{32})": "([0-9]{10})","([0-9a-z]{32})":"([0-9a-z]{32})"', html)[0]
            magic_code_group = {
                magic_code[0]: magic_code[1],
                magic_code[2]: magic_code[3]
            }

        except IndexError as err:
            raise RegexMatchError(
                f'Relative info not found in html with regex: {str(err)}') from err

        except json.decoder.JSONDecodeError as err:
            raise DecodeError(f'JSON decode error: {str(err)}') from err

        new_info = def_info.copy()
        new_info.update(magic_code_group)
        # form change
        new_info['szgjcs'] = ""
        new_info['zgfx14rfhsj'] = ""
        new_info['geo_api_info'] = old_info['geo_api_info']  # 定位
        new_info['address'] = old_info['address']
        new_info['area'] = old_info['area']
        new_info['city'] = old_info['city']
        new_info['ismoved'] = 0
        new_info['sfzx'] = old_info['sfzx']  # 在校
        new_info['sfymqjczrj'] = old_info['sfymqjczrj']  # 入境
        new_info['sfqrxxss'] = 1  # 属实
        # new_info['verifyCode'] = self.get_verify_code()  # 验证码

        self.info = new_info
        # print(json.dumps(self.info))
        return new_info

    def _rsa_encrypt(self, password_str, e_str, M_str):
        password_bytes = bytes(password_str, 'ascii')
        password_int = int.from_bytes(password_bytes, 'big')
        e_int = int(e_str, 16)
        M_int = int(M_str, 16)
        result_int = pow(password_int, e_int, M_int)
        return hex(result_int)[2:].rjust(128, '0')


# Exceptions
class LoginError(Exception):
    """Login Exception"""
    pass


class RegexMatchError(Exception):
    """Regex Matching Exception"""
    pass


class DecodeError(Exception):
    """JSON Decode Exception"""
    pass


def main(username, password, API_KEY, SECRET_KEY):
    """Hit card process

    Arguments:
        username: (str) 浙大统一认证平台用户名（一般为学号）
        password: (str) 浙大统一认证平台密码
    """

    hit_carder = HitCarder(username, password, API_KEY, SECRET_KEY)
    print("[Time] %s" % datetime.datetime.now().strftime(
        '%Y-%m-%d %H:%M:%S'))
    print(datetime.datetime.now(datetime.timezone.utc) +
          datetime.timedelta(hours=+8))

    print("打卡任务启动")

    try:
        hit_carder.login()
        print('已登录到浙大统一身份认证平台')
    except Exception as err:
        return 1, f'打卡登录失败：{str(err)}'

    try:
        ret = hit_carder.check_form()
        if not ret:
            return 2, '打卡信息已改变，请手动打卡'
    except Exception as err:
        return 1, f'获取信息失败，请手动打卡: {str(err)}'

    try:
        hit_carder.get_info()
    except Exception as err:
        return 1, f'获取信息失败，请手动打卡: {str(err)}'

    try:
        res = hit_carder.post()
        # print(res)
        if str(res['e']) == '0':
            return 0, '打卡成功'
        elif str(res['m']) == '今天已经填报了':
            return 0, '今天已经打卡'
        elif str(res['m']) == '验证码错误':
            return 1, '验证码错误'
        else:
            return 1, '打卡失败'
    except Exception:
        return 1, '打卡数据提交失败'


if __name__ == "__main__":
    username = os.environ['USERNAME']
    password = os.environ['PASSWORD']
    API_KEY = os.environ['API_KEY']
    SECRET_KEY = os.environ['SECRET_KEY']

    ret, msg = main(username, password, API_KEY, SECRET_KEY)
    print(ret, msg)
    if ret == 1:
        time.sleep(5)
        ret, msg = main(username, password, API_KEY, SECRET_KEY)
        print(ret, msg)

    if dingtalk_token := os.environ.get('DINGTALK_TOKEN'):
        ret = message.dingtalk(msg, dingtalk_token)
        print('send_dingtalk_message', ret)

    if serverchan_key := os.environ.get('SERVERCHAN_KEY'):
        ret = message.serverchan(msg, '', serverchan_key)
        print('send_serverChan_message', ret)

    if pushplus_token := os.environ.get('PUSHPLUS_TOKEN'):
        print('pushplus服务已下线, 建议使用钉钉')
        exit(-1)
