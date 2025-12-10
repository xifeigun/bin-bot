import os
import sys
import logging
import asyncio
import aiohttp
import re
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# === 1. 核心配置 (从Render环境变量读取) ===
# 你的 Token 会在 Render 后台填，这里不要改
API_TOKEN = os.getenv("TELEGRAM_TOKEN") 
# Render 自动分配的网址
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL") 
PORT = int(os.getenv("PORT", 8080))

# 如果没有配置 Token，程序直接报错退出，防止空转
if not API_TOKEN:
    sys.exit("Error: TELEGRAM_TOKEN environment variable is not set!")

# === 2. 支付宝接口配置 ===
# 这个接口非常准，专门查国内卡
ALIPAY_API = "https://ccdcapi.alipay.com/validateAndCacheCardInfo.json?_input_charset=utf-8&cardNo={}&cardBinCheck=true"

# 银行代码转中文
BANK_MAP = {
    "ABC": "农业银行", "ICBC": "工商银行", "CCB": "建设银行", 
    "BOC": "中国银行", "CMB": "招商银行", "BCOM": "交通银行", 
    "GDB": "广发银行", "CITIC": "中信银行", "SPDB": "浦发银行", 
    "CMBC": "民生银行", "CIB": "兴业银行", "CEB": "光大银行", 
    "PSBC": "邮储银行", "COMM": "交通银行", "CITIC": "中信银行"
}

# 官网映射 (为了模仿截图效果)
WEBSITE_MAP = {
    "ABC": "http://www.abchina.com",
    "ICBC": "http://www.icbc.com.cn",
    "CCB": "http://www.ccb.com",
    "CMB": "http://www.cmbchina.com",
    "BOC": "http://www.boc.cn"
}

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# === 3. 核心功能函数 ===

async def get_card_info(card_no):
    """请求支付宝接口"""
    async with aiohttp.ClientSession() as session:
        try:
            url = ALIPAY_API.format(card_no)
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('validated'): return data
        except Exception as e:
            logging.error(f"API Error: {e}")
    return None

def luhn_check(card_number):
    """Luhn 算法校验"""
    try:
        digits = [int(d) for d in str(card_number)]
        checksum = 0
        double = False
        for digit in reversed(digits):
            if double:
                digit *= 2
                if digit > 9: digit -= 9
            checksum += digit
            double = not double
        return checksum % 10 == 0
    except: return False

# === 4. 消息处理逻辑 ===

# 只要是包含数字的消息，尝试提取并查询
@dp.message() 
async def handle_message(message: types.Message):
    # 提取文本中的数字
    text = message.text or ""
    # 简单的正则：如果包含 "查卡" 或者直接发数字
    card_no = re.sub(r'\D', '', text)

    # 只有当提取出的数字长度像卡号(>10位)时才触发，避免误触
    if len(card_no) < 10:
        return 

    # 查接口
    api_data = await get_card_info(card_no)
    
    # 算校验位
    luhn_pass = luhn_check(card_no)
    luhn_str = "本卡校验为正确" if luhn_pass else "校验不通过(可能是无效卡)"

    if api_data:
        bank_code = api_data.get('bank')
        card_type = api_data.get('cardType') # DC=储蓄, CC=信用
        
        bank_name = BANK_MAP.get(bank_code, bank_code)
        
        type_name = "借记卡"
        if card_type == "CC": type_name = "信用卡"
        if card_type == "SCC": type_name = "准贷记卡"
        if card_type == "PC": type_name = "预付费卡"

        website = WEBSITE_MAP.get(bank_code, "https://www.unionpay.com")

        # 这里的“归属”因为免费API查不到具体城市，为了格式好看，写个通用提示
        # 如果你一定要天津，需要几百兆的离线库，Render放不下
        region = "中国 / 全国通用" 

        reply_text = (
            f"银行卡查询成功：\n"
            f"卡号： `{card_no}`\n"
            f"银行： {bank_name}\n"
            f"卡种： {type_name}\n"
            f"归属： {region}\n"
            f"官网： {website}\n"
            f"验证： {luhn_str}"
        )
        await message.reply(reply_text, parse_mode=ParseMode.MARKDOWN)
    
    # 如果接口没查到，但符合Luhn算法（可能是国外卡），简单回复
    elif luhn_pass:
        await message.reply(f"卡号：`{card_no}`\n状态：未匹配到国内银行信息\n验证：{luhn_str}", parse_mode=ParseMode.MARKDOWN)

# === 5. Webhook 启动入口 ===

async def on_startup(bot: Bot):
    # Render 启动时会自动告诉 Telegram 把消息发到哪里
    webhook_url = f"{WEBHOOK_HOST}/webhook"
    logging.info(f"Setting webhook to: {webhook_url}")
    await bot.set_webhook(webhook_url)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
