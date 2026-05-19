import os
import sys
import pandas as pd
import akshare as ak
import requests
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

def get_market_hotspots():
    """1. 抓取 A 股盘中行业资金流向和吸金个股"""
    print("正在获取 A 股盘中热点与资金流向...")
    try:
        # 获取今日行业资金流向排行
        df_industry = ak.stock_sector_fund_flow_rank(indicator="今日")
        top_industries = df_industry.head(3)['板块名称'].tolist()
        
        # 获取个股资金流入排行
        df_individual = ak.stock_individual_fund_flow_rank(indicator="今日")
        df_individual['主力净流入-净额'] = pd.to_numeric(df_individual['主力净流入-净额'], errors='coerce')
        df_top_stocks = df_individual.sort_values(by='主力净流入-净额', ascending=False).head(15)
        
        stocks_info = []
        for _, row in df_top_stocks.iterrows():
            stocks_info.append({
                "code": row['代码'],
                "name": row['名称'],
                "price": row['最新价'],
                "change_percent": row['涨跌幅'],
                "net_inflow_w": round(row['主力净流入-净额'], 2)
            })
            
        return top_industries, stocks_info
    except Exception as e:
        print(f"A 股数据抓取失败: {e}")
        return [], []

def ask_ai_for_advice(industries, stocks):
    """2. 呼叫大模型结合资金流向给出精选买点"""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LITELLM_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com/v1"
    model = os.getenv("LITELLM_MODEL") or "deepseek-chat"

    if not api_key:
        print("⚠️ 未检测到任何 AI 密钥，将直接发送原始数据快照。")
        return None

    # A 股盘中选股 Prompt
    prompt = f"""
    你是一位精通中国 A 股短线题材游资思维和资金流重量化策略的投研专家。
    请根据以下盘中真实的实时数据，推导当前市场的核心主线，并筛选出可买入的股票信息。

    【当前主力资金最青睐的行业板块】：{', '.join(industries)}
    
    【今日主力资金净流入前15名的个股异动数据】：
    {pd.DataFrame(stocks).to_string(index=False)}

    请重点完成以下深度分析：
    1. 【核心主线推导】：结合行业和吸金个股，指出当前盘中最强的题材风口是什么？
    2. 【潜力标的严选】：从上述个股中，严选出 2 只最值得关注的股票（要求：涨幅适中未暴涨、有板块效应、资金持续流入、排除ST股）。
    3. 【盘中操作指南】：对这 2 只股票分别给出：
       - 【个股名称与代码】
       - 【核心买入逻辑】（为什么主力在买？）
       - 【盘中建议买入点位/区间】（请结合当前价，给出合理的低吸或突破买点）
       - 【防守止损位】
    
    请严格使用清晰的 Markdown 格式输出。
    """

    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        response = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"AI 投研分析失败: {e}"

def send_email(content):
    """3. 自动发送邮件模块"""
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receivers = os.getenv("EMAIL_RECEIVERS")
    sender_name = os.getenv("EMAIL_SENDER_NAME", "A股盘中量化助手")

    if not sender or not password or not receivers:
        print("⚠️ 邮件服务配置不完整（EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVERS），跳过邮件发送。")
        return

    receiver_list = [r.strip() for r in receivers.split(",") if r.strip()]
    now_str = datetime.now().strftime('%H:%M')
    subject = f"🔥 A股盘中风口与资金选股提醒 ({now_str})"

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #d32f2f; border-bottom: 2px solid #d32f2f; padding-bottom: 10px;">📊 {subject}</h2>
        <div style="background-color: #f9f9f9; padding: 15px; border-left: 4px solid #d32f2f; margin-bottom: 20px; white-space: pre-wrap;">
{content}
        </div>
        <p style="font-size: 12px; color: #888; text-align: center; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px;">
            本邮件由 GitHub Actions 自动化量化系统发出。入市有风险，投资需谨慎。
        </p>
    </body>
    </html>
    """

    try:
        message = MIMEText(html_content, 'html', 'utf-8')
        message['From'] = Header(f"{sender_name} <{sender}>", 'utf-8')
        message['To'] = Header(", ".join(receiver_list), 'utf-8')
        message['Subject'] = Header(subject, 'utf-8')

        smtp_server = "smtp." + sender.split("@")[-1]
        server = smtplib.SMTP_SSL(smtp_server, 465, timeout=15)
        server.login(sender, password)
        server.sendmail(sender, receiver_list, message.as_string())
        server.quit()
        print("✅ 选股清单已成功发送至您的邮箱！")
    except Exception as e:
        print(f"邮件发送失败: {e}。")

if __name__ == "__main__":
    industries, stocks = get_market_hotspots()
    if not stocks:
        print("未获取到有效的资金流向，退出。")
        sys.exit(0)
        
    ai_report = ask_ai_for_advice(industries, stocks)
    
    if ai_report:
        send_email(ai_report)
    else:
        raw_content = f"**当前热门行业**: {', '.join(industries)}\n\n**主力净流入前5个股**:\n"
        for s in stocks[:5]:
            raw_content += f"- {s['name']}({s['code']}): 净流入 {s['net_inflow_w']} 万, 当前价 {s['price']} ({s['change_percent']}%)\n"
        send_email(raw_content)
